# ADR-019: Doc-Type Precedence in Multi-Source Regulation Merge

**Date:** 2026-05-12
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** ingestion, correction-handling, source-arbitration

---

## Context

PRD 001 R5 specifies the merge rule for sources that publish corrections to annual
regulations: *"corrections are processed after booklets on every run, with the
latest-dated source winning."* The intent is unambiguous: a correction issued on
date Y must override a booklet published on date X if Y > X.

The original S03.4 spec (Black Bear booklet + correction PDF handling) codified
this as "MAX `publication_date` wins" — read each cell from the source with the
highest `publication_date`. Call this **Option A**.

S03.4 UAT (2026-05-12) against the live Montana 2026 set exposed a defect in
this literal interpretation. The relevant `sources.yaml` entries pin
`publication_date` to each PDF's HTTP `Last-Modified` header (per the
2026-05-07 URL-discovery sweep):

  - Black Bear booklet: `2026-04-27`
  - Black Bear correction: `2026-03-18`

The booklet's Last-Modified post-dates the correction's by ~6 weeks. Under
Option A's literal rule, the booklet wins on every cell — the correction is
effectively ignored, the merge is a no-op, and the artifact silently reflects
pre-correction state. That is the opposite of the spec's intent.

The root cause is that HTTP `Last-Modified` is not a publication-semantic
signal. It reflects when the CDN's PDF file was last touched, which can be
later than the document's content publication date (e.g., a regenerated PDF,
a metadata refresh, a CDN cache key bump, a fixed typo on a non-regulatory
page). Across doc-types this is especially unreliable: a booklet that gets a
post-correction touch-up — exactly the situation that *should* indicate the
correction was applied to the source — will, under Option A, defeat the
correction at merge time.

PDFs sometimes carry an internal publication date on their cover page, but
extracting it reliably across heterogeneous agency outputs is its own
project. We needed a rule that works without trusting a brittle date signal.

## Decision

**Doc-type rank takes precedence over `publication_date` in the multi-source
merge.** Concretely, for each cell:

1. **Doc-type rank:** `'correction'` > `'annual_regulations'`. The cell takes
   its value from the source with the highest doc-type rank that touches it.
   `publication_date` is irrelevant in this comparison.
2. **Same-doc-type tiebreak by date:** if two sources of the same `document_type`
   touch the same cell, the one with the higher `publication_date` wins.
3. **Same-doc-type, same-date conflict:** raise `CorrectionConflictError` with
   both `source_id`s in the message. This catches operator mistakes (two
   corrections with the same publication date pointing at the same cell) and
   prevents silent ordering-of-iteration resolution.
4. **Row-level source attribution as V1 simplification:** when a row's cells
   are touched by corrections, the row's `source_id` + `source_publication_date`
   update to the row-level winning correction's source. Ties at row level
   (multiple corrections touch different cells of the same row, same doc-type,
   same date) resolve by lex-smallest `source_id` for deterministic provenance.
5. **V1 rank table is exhaustive; other doc-types fail loud.** The
   `document_type` Literal currently enumerates five values (per
   `ingestion/ingestion/lib/schema.py` and `mcp-server/src/types/schema.ts`):
   `annual_regulations`, `rule_change`, `emergency_order`, `correction`,
   `gis_layer`. ADR-019 ranks only the two participating in V1's regulation-text
   merge path: `correction` > `annual_regulations`. Sources of any other
   doc-type appearing in a regulation-text merge MUST fail loud at merge time
   with a descriptive error — they MUST NOT participate silently with an
   implicit default rank. If a future state adapter needs to merge
   `rule_change` or `emergency_order` (intuitively `emergency_order > correction`,
   but that ordering is deliberately not declared here), this ADR must be
   amended first to add the rank explicitly.

`document_type` values are validated against the type-layer Literal per ADR-014,
so a typo in `sources.yaml` (`'corrections'`, `'amendment'`, etc.) fails at
load time and never reaches the merge stage. A missing or null `document_type`
field also fails Literal validation at load. A *valid* Literal value not
ranked by this ADR (e.g., a future `emergency_order` source in a merge)
fails at merge time, not load time — load doesn't know whether the source
will participate in a merge.

## Reasoning

### Why doc-type is the canonical signal

`document_type` is hand-curated in `sources.yaml` and explicitly enumerated in
the type layer (per ADR-014). When an operator marks a PDF as
`document_type='correction'`, they are asserting "this document amends prior
publications." That assertion is unambiguous, doesn't rely on third-party
metadata, and survives CDN refreshes. It is the right load-bearing signal for
arbitration semantics.

`publication_date` remains useful — it orders multiple corrections, surfaces
freshness questions, and supports audit-trail review — but it does not carry
"supersedes" intent across doc-types.

### Why per-cell value arbitration is still the rule

This ADR does not change *which cells* the correction touches — the
`CorrectionOperation` list from the Pass 2 correction artifact still names
the specific cells affected. The ADR changes *how the winner is picked for
each touched cell*. Cells the correction does not touch keep the booklet's
value (no doc-type comparison is made on untouched cells).

ADR-017 §4 explicitly states "Demotion applies at the per-row level" (§4 ¶ 2);
ADR-019 makes the once-per-row *firing* explicit at the implementation layer
so a row touched by N corrections is demoted exactly once, not N times — a
real defect class that S03.4 cubic-review iteration caught and locked.

### Why row-level source attribution is a V1 simplification

True cell-level source attribution would require `BmuRowExtraction` (and
analogous DTOs in future state adapters) to carry one `source_id` +
`source_publication_date` per cell rather than one per row. That is a real
schema change with downstream implications for `regulation_record` ingestion
in S03.6 and beyond. The V1 simplification — update row-level provenance to
the winning correction when *any* cell of the row is touched — keeps the
arbitration rule cleanly defined while deferring the schema split to M2 review.

The audit trail is not lost: `corrections-2026-03-18.json` (the Pass 2
correction-extraction artifact, committed) carries every `CorrectionOperation`
with its `source_id` and target cell. A consumer that needs cell-level
provenance can reconstruct it from that artifact + the booklet artifact.

**Terminology note:** "Pass 1 / Pass 2 / Pass 3" in this ADR refers to the
three *artifact-producing phases* of the per-state correction pipeline
(base extraction → correction extraction → merged output, the
`black-bear-2026-base.json` / `corrections-2026-03-18.json` / `black-bear-2026.json`
triplet). The merge function `_merge_with_corrections` is itself one Pass
(Pass 3) composed of three inner **Stages** (per-cell value arbitration →
field-value apply → row-level provenance + tier-demote). The two layerings
sit at different levels and should not be conflated.

### Why the same-cell equal-date tiebreaker is fail-loud, not silent

`CorrectionConflictError` on same-cell equal-date collisions is unchanged from
the original spec (line 395). The doc-type rule resolves cross-doc-type
collisions, but two corrections at the same date targeting the same cell is
still a real operator-side ambiguity that deserves operator attention. The
2026-03-18 correction is the only V1 correction so this never fires in M1.

**M2 operator-recovery path** (named here so it's specified, not improvised):
when `CorrectionConflictError` fires on a same-day collision, the operator
has two clean recoveries: (a) re-pin one source's `publication_date` in
`sources.yaml` to its actual content-publication date if Last-Modified is
misleading (the same fix pattern as the original Option-A defeat), or
(b) split a multi-source correction PDF into distinct `sources.yaml` entries
so each correction carries its own `source_id` and the lex-smallest
tiebreaker resolves at row level. `CorrectionConflictError` includes both
`source_id`s in its message to make either recovery direct.

### Why row-level lex-smallest-source_id tiebreak is deterministic

When a row is touched by N corrections with the same doc-type and same
publication date, picking the winning correction by lex-smallest `source_id`
is deterministic regardless of dict-insertion order. Without an explicit
tiebreak, the row's `source_id` depended on iteration order — a real
correctness defect caught by S03.4 cubic-review iteration before merge to
main.

## Alternatives considered

1. **Keep Option A; require operators to manually override `publication_date`
   in `sources.yaml` when Last-Modified is wrong.** Rejected: pushes a
   load-bearing semantic decision onto the operator with no automation;
   regresses the S03.7 lesson that "spec tables encoding URL guesses are
   pre-validated assumptions" (operators don't know which Last-Modifieds are
   reliable); reintroduces the same defect class for any state adapter where
   the operator forgets the override.
2. **Keep Option A; extract publication date from PDF cover pages instead of
   HTTP Last-Modified.** Rejected as primary signal: cover-page date
   extraction is per-agency-format brittle (FWP's cover layout differs from
   Colorado Parks and Wildlife's); failure modes are extraction bugs, not
   data-quality flags; would still produce a date-precedence rule that needs
   a separate doc-type override for corrections issued during a
   pre-publication preview window. Worth considering as a supplemental signal
   in M2+ if doc-type-precedence proves insufficient.
3. **Keep Option A; warn loudly when a `correction` has an earlier date than
   its target booklet.** Rejected: shifts the burden from the merge rule to
   the operator's attention; the warning is non-actionable without a separate
   override mechanism; produces noise on every Montana run for V1.
4. **Per-cell source attribution in V1.** Rejected for scope: requires a
   `BmuRowExtraction` schema split and equivalent changes for future state
   adapters; M1 doesn't need it; deferred to M2 review with the audit trail
   preserved in the committed Pass 2 artifact.
5. **Use the existing `SourceCitation.supersedes` field as the arbitration
   signal** instead of `document_type`. Note: `supersedes: str | None`
   already exists in the schema (Pydantic line 77, TypeScript line 55) and
   is populated downstream in correction rows. Rejected for V1: shifts the
   load-bearing assertion from `document_type` (typed-enum-enforced,
   operator-curated, one of five known values) to a per-source
   `supersedes` pointer that is unvalidated free text and that supports
   multi-hop chains (a correction supersedes another correction supersedes
   the original booklet). The current rule is a single-step doc-type
   comparison; switching to `supersedes` would require a graph-resolution
   step plus typo/cycle defenses. The `supersedes` field continues to be
   used for downstream display + audit (each correction-touched row
   carries `supersedes: <booklet_id>` in the merged artifact), not for
   arbitration. M2 revisit if a state surfaces a multi-hop correction
   chain that doc-type-precedence can't disambiguate.
6. **Promote `document_type` to a `(value, rank)` pair via an ADR-014
   amendment** so future doc-types get programmatic ranks rather than
   ad-hoc ADR-019 amendments. Considered as a structural refinement.
   Rejected for V1 because two ranked values (`correction`,
   `annual_regulations`) is below the threshold where a sortable integer
   adds clarity over a small enumerated rule list. Revisit when a third
   merge-participating doc-type lands (e.g., `emergency_order`) — at that
   point a `(value, rank)` table is probably the right refactor.

## Consequences

- **PRD 001 R5 wording needs reconciliation.** "Latest-dated source winning"
  is technically still true *within doc-type*, but the cross-doc-type rule is
  now doc-type-precedence. PRD update is housekeeping for the next PM-led
  PRD review pass (or before E04 planning, whichever comes first); this ADR
  is the audit trail in the interim. PM does not modify PRDs autonomously
  per established convention. Proposed reconciliation wording when the
  update lands: *"Corrections always supersede annual regulations regardless
  of publication date. Within the same `document_type`, the source with the
  latest `publication_date` wins, with `CorrectionConflictError` on
  equal-date same-cell collisions."*
- **Every future state adapter inherits this rule.** M2 Colorado, Wyoming,
  Idaho, etc.: whenever a state publishes a correction PDF that targets an
  annual regulations PDF, the doc-type-precedence rule applies. The merge
  helper in shared code (when one is built — currently per-state) follows
  this contract.
- **`document_type` values must be reliable.** `document_type='correction'` is
  now load-bearing for merge semantics, not just for provenance display.
  ADR-014's type-layer Literal validation is the enforcement gate. Adding a
  new doc-type value (e.g., `'errata'`, `'addendum'`, `'amendment'`) requires
  an ADR amendment to this ADR to specify its rank relative to existing
  values.
- **Cell-level source attribution remains a V1 simplification.** M2 review
  may revisit, especially if a state adapter surfaces a use case where
  per-cell provenance materially affects S03.6+ ingestion.
- **`max(...)` / `min(...)` with comparable ties anywhere in the merge path
  must carry an explicit secondary key for deterministic semantics.** Added
  as a known-pitfalls entry during S03.4 cubic-review iteration; this ADR
  records the principle: arbitration determinism is a first-class correctness
  requirement, not a happy-path assumption.

## Reference implementation

`ingestion/states/montana/extract_black_bear.py::_merge_with_corrections`
(merged via PR `ab09e82` 2026-05-12). The three-stage refactor that emerged
from S03.4 cubic-review iteration — per-cell value arbitration → field-value
apply → row-level provenance + tier-demote (applied once per touched BMU, per
ADR-017 §4's per-row single-step rule) — is the canonical pattern. The
function's docstring (lines 1631-1665 of `extract_black_bear.py`) carries an
embedded "Option B — doc-type precedence" explanation that mirrors this ADR
inline; future readers of the function don't have to chase the ADR pointer.
Regression tests in `ingestion/tests/test_extract_black_bear.py::TestMergeWithCorrections`
lock the contract:

- `test_real_world_option_b_correction_wins_despite_earlier_date` (line 1085) — Option B fires correctly even when the correction's date predates the booklet's
- `test_date_collision_tiebreaker_raises_conflict_error` (line 1122) — same-cell equal-date raises `CorrectionConflictError` with both source ids
- `test_row_provenance_tiebreaker_is_lex_smallest_source_id` (line 1235) — row-level lex-smallest tiebreak when multiple same-date corrections touch one row
- `test_multi_field_row_demoted_once_and_provenance_is_max_date` (line 1278) — `demote_one_tier` fires exactly once per touched BMU regardless of how many fields the corrections cover
