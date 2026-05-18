# Draw Mechanics Deferrals (Q12)

This file tracks deferrals related to the `parameters` escape-hatch field on `draw_spec` (Q12 from the E03 epic, per PRD 001 §"Out of scope"). If extraction during E03 surfaces a draw mechanic that cannot be expressed within the structured `draw_spec` fields and appears to require `parameters`, the implementer flags it here per the operational definition in this directory's README.

Per E03 epic line 32: do not exercise the `parameters` field during E03. Flag-and-defer to this file for M2 handoff.

---

## Items

<!-- S03.7+ implementers: append entries here when a draw mechanic requires deferral.
     Format: ### <hunt_code or pattern> — brief description
     Include: source span, which structured field(s) were insufficient, why parameters was tempting. -->

### `900-20` (Antelope STATEWIDE) — "First and only choice. ArchEquip only."

**Source:** DEA booklet `mt-fwp-dea-2026-booklet-2026-04-27.pdf`, page 137 (STATEWIDE row at the start of the antelope section).

**Verbatim text:** "First and only choice. ArchEquip only."

**Structured fields insufficient:**
`ChoiceConfig` has no `ordering_rule` semantic. "First and only choice" implies
a single-choice priority-position constraint, not a choice-count constraint —
it is NOT expressible as `count=1` alone. The `AllocationPool.selection` Literal
enum (`"rank_ordered_by_points"`, `"unweighted_random"`,
`"squared_weighted_random"`, `"linear_weighted_random"`) does not model
ordering-position semantics.

**Why `parameters` was tempting:**
`parameters["ordering_rule"] = "first_and_only"` would capture the semantic, but
Q12 (ADR-012) defers all `parameters` use to M2 — every V1 draw_spec ships with
`parameters=null`.

**M2 recommendation:**
Either (a) promote `parameters["ordering_rule"]` as a first-class optional
field on `ChoiceConfig`, or (b) add an `ordered_choice_position: int | null`
field to `ChoiceConfig` to express "this license is always the hunter's first
and only choice."

**S03.8 action:**
NO `draw_spec` written for `900-20`. The STATEWIDE classification in S03.7's
`_DEA_LICENSE_KIND_HEURISTIC` already routes this row to `kind='statewide'`
(not `limited_draw`), so it falls out of S03.8's filter cleanly.
`license_tag.draw_spec_key` stays NULL. `license_tag.verbatim_rule` carries the
full source text including the "first and only choice" prose. No WARN log is
needed at run time — the skip is structural, not exceptional.

---

### MT NR-cap structure (MCA Title 87-2-106's 10% NR cap)

**Source:** Montana Code Annotated Title 87, Chapter 2, Part 1, §106 — quoted
verbatim on DEA booklet `mt-fwp-dea-2026-booklet-2026-04-27.pdf` p. 12
("Obtain A License Or Permit" section, second paragraph): "By state law,
nonresidents are limited to, but not guaranteed, 10 percent of the license
and/or permit quota."

**Verbatim text:** "By state law, nonresidents are limited to, but not guaranteed, 10 percent of the license and/or permit quota."

**Structured fields insufficient:**
V1 ships every `draw_spec.pools` as `[AllocationPool(share=1.0, selection="unweighted_random")]` —
a single pool that elides the resident/nonresident split. A faithful model
would split into two `AllocationPool` entries with `share=0.9` (resident-
eligibility) + `share=0.1` (nonresident-eligibility-or-resident-overflow),
governed by MCA Title 87's NR-quota rule as a hard ceiling rather than a pool
share. The current `AllocationPool` schema cannot represent a hard cap that
also accepts resident overflow.

**Why we didn't model it in V1:**
S03.7's residency extraction collapsed every DEA `license_tag` to
`residency="both"` (the artifact does not carry the resident/nonresident
allocation split per-hunt; the 10% cap is policy at the state level, not per-
row in the DEA tables). Faithfully modeling the cap requires:

1. A residency-aware allocation extraction pass (out of S03.3/S03.7 scope)
2. A draw mechanic that treats the cap as a hard ceiling with overflow
   semantics (out of `AllocationPool`'s current expressive range)

**M2 recommendation:**
Extract MT NR-cap rules from the DEA booklet's "Important Information" /
front-matter chapter (pp. 12-14); promote `pools` to two-pool with
resident/nonresident eligibility (and overflow tie-break); document the
cap-vs-share semantic in an ADR-012 addendum.

**S03.8 action:**
Single-pool `[AllocationPool(share=1.0, selection="unweighted_random")]` ships
on every V1 `draw_spec` row. `license_tag.verbatim_rule` carries the per-row
DEA section's verbatim_text via S03.7's section-scoped fallback; per-row NR-cap
prose is not extracted in V1 (the MCA quote lives in the booklet's
front-matter, not in the species sections).

---

### Per-HD allocation caps for cross-listed B licenses (HD 210 case)

**Source:** DEA booklet `mt-fwp-dea-2026-booklet-2026-04-27.pdf`, p. 53 row 7
(HD 210, home), p. 53 row 21 (HD 211), p. 54 row 12 (HD 212), p. 57 row 13
(HD 216). `Elk B License: 210-03` cross-listed across 4 HDs with conflicting
quota values.

**Verbatim text (identical on all 4 rows, OPPORTUNITY SPECIFIC DETAILS column):**
"Valid on private lands in HDs 211, 212, 216 and south portion of 210
(Rattling Gulch-Henderson Creek)."

**Structured fields insufficient:**
The home-HD quota=300 is the total drawable count for the license; the cross-
listed mentions show quota=200, which the booklet language describes as a
per-HD allocation cap (only 200 of the 300 can be hunted in any one cross-
listed HD). The current `draw_spec` schema has no field for jurisdiction-keyed
per-HD allocation caps — `AllocationPool.eligibility` carries residency / point
/ guided but not per-HD caps.

**Why we didn't model it in V1:**

- Modeling per-HD caps requires a new schema field (jsonb keyed by
  jurisdiction_code) or use of `parameters` (Q12 escape hatch, deferred).
- The cap-vs-quota distinction is observable only by reading the booklet
  language; no per-row structured field carries the "this is a cap, not a
  separate quota" semantic.
- Currently exactly 1 affected entry across all V1 Montana data; investing in
  a new schema field for a single case is premature.

**V1 action (S03.8):**
`_KNOWN_CROSS_LISTING_OVERRIDES` in
`ingestion/states/montana/load_draw_specs.py` records the canonical quota
(`("Elk B License: 210-03", 2026): {"quota": 300, ...}`) and a WARN log fires
at run time naming the conflict + rationale. The cross-listed quota=200 values
are dropped from `draw_spec.quota` but the home-HD verbatim_rule on each
per-HD `license_tag` preserves the "Valid on private lands in HDs 211, 212, 216
and south portion of 210" language.

**M2 recommendation:**
Evaluate three options (see [docs/open-questions.md Q17](../../open-questions.md)):
(a) `parameters` jsonb (ADR-012 escape hatch); (b) new `per_hd_allocations`
schema field; (c) hunt-code disambiguation. Decision criteria: cross-state
pattern prevalence + MCP `get_tag_requirements` consumer needs.

**Affected V1 entries:** 1 (HD 210). Re-survey when MT 2027 booklet ships and
when CO / WY data lands in M2.
