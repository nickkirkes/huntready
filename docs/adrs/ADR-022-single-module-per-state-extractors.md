# ADR-022: Single-Module Per-State PDF Extractors

**Date:** 2026-06
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** ingestion

---

## Context

Each state's PDF extractor is one `.py` module organized into labelled sections — probe notes → constants / TypedDicts → cleanup helpers → hunt-code / season-window parsing → table-block parsing → confidence assignment → orchestrator → CLI. They are large: MT `extract_dea.py` (1,655 LOC), `extract_legal_descriptions.py` (1,372), `extract_black_bear.py` (3,603); CO `extract_big_game.py` (2,922 after S06.3.1's R16 row-fusion port). There is no multi-module or package-structured extractor anywhere in the repo.

Code reviewers — cubic included — recurrently raise a P2/P1 "monolithic module, split into focused modules, hard to evolve" finding against these files. It surfaced **three times** against CO `extract_big_game.py` during S06.3 alone, and again against the S06.3.1 R16 change. Each instance was declined, with the rationale recorded informally in `.roughly/known-pitfalls.md` and tracked as E06 Known Issue #9. The cost of the informal disposition is that the question gets re-litigated every time someone touches an extractor: there is no canonical, citable decision a reviewer can be pointed at. This ADR makes the decision durable.

## Decision

Each state's PDF extractor remains a **single labelled-section `.py` module**. The recurring "split this into modules" review finding is a valid observation but is **declined by citing this ADR**. Extractor modularization is reopened only by a future ADR that supersedes this one and applies the new structure **uniformly across every state extractor in a single PR** — never as a piecemeal, per-story refactor at review time.

## Reasoning

The finding's core worry — that coupling makes a large file unsafe to change — is the one risk the project has already mitigated by other means. Every extractor is locked by a per-state test suite: artifact-regression assertions pin exact section / row / confidence counts and the artifact SHA-256, per-layer unit tests cover the parsing helpers and the splitter, and AST isolation guards (`TestNoColoradoLeakIntoSharedLib`, no-`layout=True`) enforce boundaries. A change that breaks one part of the file fails a test immediately and deterministically, not silently in production. Module boundaries would add the same protection a second time, at the cost of a structure the rest of the codebase does not use.

Uniformity is load-bearing. ADR-005 frames each `ingestion/states/<state>/` adapter as an isolated unit; the extractor module *is* that adapter's extraction boundary. Splitting one state into a package while the other three stay single-module makes the set *less* consistent, not more — a reader who learns one extractor's shape should be able to navigate all of them. The labelled-section convention already provides intra-file wayfinding; the sections are the de-facto modules, minus the import ceremony.

Finally, modularization is a project-wide architectural change — a structure that applies to every state plus, potentially, a shared extraction framework. Deciding it inside a single story's code review, against just-merged, cubic-clean, fully-tested code, inverts the cost/benefit: high blast radius, no functional gain, and it couples an architecture decision to whichever story happened to touch the file. That is an ADR's job, authored deliberately — not a reviewer's inline ask.

## Alternatives Considered

- **Split all extractors into packages now.** Rejected as premature and mis-vehicled: it is an ADR-level, all-states-at-once change, not something to do piecemeal while implementing an unrelated feature. If pursued, it is a future ADR superseding this one.
- **Split only the largest extractor(s) past a LOC threshold.** Rejected: produces exactly the inconsistency this decision avoids — some states packages, others single files — for a cosmetic line-count win.
- **Keep deciding per review (the prior informal status quo).** Rejected: that *is* the re-litigation this ADR ends. The decision was already made three times the same way; not recording it formally is the defect.
- **Extract shared parsing logic into `ingestion/lib/`.** Partially adopted, and the boundary is the point: genuinely state-agnostic primitives already move to lib (e.g. `pdf.write_extraction_artifact`, the `pdf_fetch` helpers). State-specific cleanup rules, hunt-code grammars, and table layouts stay per-extractor because they are not shared. This ADR governs the per-state remainder, not the shared layer.

## Consequences

### Positive

- Reviewers (human and cubic) get a canonical citation; the recurring "monolithic module" finding is dispositioned in one line instead of re-argued per story.
- The per-state adapter boundary (ADR-005) stays uniform across all four extractors — learn one, navigate all.
- Merged, audited, cubic-clean extractor code is not churned by speculative structural refactors.

### Negative

- The files stay large and genuinely harder to skim than a package would be; new-contributor onboarding pays a real cost that this ADR accepts rather than removes.
- A future brochure year that introduces a new fusion pattern or column layout adds yet more branching to an already-large file. The mitigation is the test suite and the labelled-section structure, not smaller files.
- Declining a recurring reviewer finding by policy risks normalizing dismissal of *other* findings; this ADR's scope is narrow — it disposes of the module-size finding specifically, not maintainability findings generally.

### Neutral

- The decision is reversible by a superseding ADR. **Revisit trigger:** when a genuinely shared cross-state parsing layer emerges that three or more states would import (the `write_extraction_artifact` precedent, but substantially larger), OR when the team commits to a uniform extractor-framework refactor — at which point a new ADR specifies the package structure and supersedes this one.
- `.roughly/known-pitfalls.md` and E06 Known Issue #9 now point at this ADR as the authoritative record.

## Links

- [ADR-005](ADR-005-python-for-ingestion-typescript-for-serving.md) — per-state adapter isolation; the extractor module is the adapter's extraction boundary
- [ADR-001](ADR-001-authority-preserved.md) — fail-loud discipline the test suites enforce
- [ADR-008](ADR-008-verbatim-regulation-text.md) — verbatim discipline (no-`layout=True` AST guard, docstring grep-parity) — part of the per-extractor test surface
- [`.roughly/known-pitfalls.md`](../../.roughly/known-pitfalls.md) — "Extractors are one module per state" entry; this ADR is its formal record
- [`docs/planning/epics/E06-colorado-regulation-text-ingestion.md`](../planning/epics/E06-colorado-regulation-text-ingestion.md) §"Known Issues to Escalate" #9 — the tracked finding this ADR closes
- [`ingestion/states/colorado/extract_big_game.py`](../../ingestion/states/colorado/extract_big_game.py) — the file most often flagged (2,922 LOC)
