# Deferred: Closure Temporal Anchors

**Survives past M1** per ADR-017 §6 (deferred-items directory is not deleted at the m1 tag).

---

## Spring Season Closure Temporal Anchor (V1 Deferral)

**Source:** S03.4, 2026 Montana Black Bear booklet p. 7

The Spring Season Closure paragraph reads:

> Spring Season Closure: BMUs 300, 301, 319, and 580 are subject to close, with regular public notice, at any point after May 31 if the cumulative spring harvest exceeds 37% female black bears.

The temporal anchor ("at any point after May 31") has no structured field in `ClosurePredicate`. Current `ClosurePredicate` fields: `kind`, `threshold_percent`, `threshold_sex`, `notification_channel`, `observation_channel`, `verbatim_rule`.

**V1 decision:** keep the temporal anchor in `verbatim_rule` only. Do NOT invent a structured field for a single-state, single-occurrence pattern.

**Future ADR candidate:** if this pattern recurs in another state's regulations (a date-anchored quota threshold), draft an ADR adding `effective_after: date | None` to `ClosurePredicate`. The pattern to watch for: a closure that is conditional on both a quota threshold AND a calendar gate ("after [date]"). Per ADR-017 §6, this file survives past M1 to track the pattern.

Reference: S03.4 spec § "Closure temporal-anchor handling" (epic line 400).
