# ADR-007: Montana and Colorado as Seed States

**Date:** 2026-04
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** scope, ingestion

---

## Context

V1 covers two states out of fifty. The choice is loadbearing: the schema's job is to accommodate the full range of U.S. hunting regulation without losing its shape, and the seed states are the only evidence V1 has that it does. Two similar states produce a schema well-shaped for a narrow slice; two deliberately different states force the schema to confront real structural variance early. The candidate set is the Western big-game cluster — Montana, Colorado, Wyoming, Idaho, Utah, Washington — where HuntReady's primary user operates.

## Decision

V1 ingests Montana and Colorado; Wyoming, Idaho, Utah, and Washington are deferred.

## Reasoning

Montana is the structurally stress-tested case on the regulation-text side. MT FWP publishes five species-specific booklets on a documented annual/biennial cycle, with a fixed-column per-HD regulation table, and with correction PDFs as a first-class publication type (a 1-page correction to the 2026 Black Bear booklet was published 2026-03-18, the day after the base). The Montana investigation surfaced nine schema pressure points — multiple named seasons per row, A/B-license split, closure predicates as prose, region-specific reporting obligations, landowner preference as a quota sub-pool — that moved the schema from v1 to v2 before any data was loaded. Montana's ArcGIS MapServer exposes forty feature layers with HDs, BMUs, CWD zones, and Portions as distinct overlay geometries — the evidence base for the v2 six-entity decomposition.

Colorado is deliberately the hard state on the tag-mechanics side. CPW runs a three-stage annual cycle (primary May, secondary late June, weekly leftovers), an 80/20 hybrid between rank-ordered preference points and a random pool for applicants with ≥5 points, and non-resident ceilings that vary with three-year rolling point averages. Verifying that `draw_spec` can model Colorado — alongside Wyoming's 75/25 split, New Mexico's statutory three-pool carve-out, and Utah's squared bonus weighting — is how V1 earns the right to claim the schema generalizes. Colorado's GMU boundaries come from the CPW ArcGIS FeatureServer (186 big-game polygons, no auth).

Depth over breadth. If the schema holds against Montana's text complexity and Colorado's draw complexity, V2 state onboarding is adapter work, not schema work.

## Alternatives Considered

**Montana and Wyoming.** Wyoming's 75/25 split is similar enough to Colorado's that it would not stress-test the schema as hard.

**Montana and Idaho.** Idaho's controlled-hunt system is point-free for most hunts and would leave preference-point modeling unverified.

**Colorado alone, going deeper.** One state cannot prove the schema generalizes; "multi-state" is a property only once two are live.

**All four Western states, shallower.** Rejected on V1 time budget and depth-before-breadth.

## Consequences

### Positive

- Schema is stress-tested on both dimensions of real variance (text structure, tag mechanics) before any additional state lands.
- V2 state onboarding is adapter work on a validated schema, not schema rework under deadline pressure.
- The public demo shows two real, different states, which reads as "multi-state" rather than a placeholder.

### Negative

- Major hunting destinations — Wyoming, Idaho, Utah, Washington — are absent from V1, and any reviewer or user whose hunt is planned there will find HuntReady unhelpful.
- Colorado's draw complexity is a meaningful share of the V1 ingestion budget; if Montana runs long, Colorado is the piece at risk of being half-done.
- Each new state introduces its own source-evaluation work, and V1 evidence does not yet tell us how much that varies.

### Neutral

- This ADR picks the two V1 states; it does not pick V2's. The order Wyoming/Idaho/Utah/Washington will be decided in a later ADR.

## Links

- [ADR-006](ADR-006-schema-versioned-from-day-one.md) — The pressure points Montana and Colorado surface are why versioning matters.
- [`docs/research/montana-source-structure-findings.md`](../research/montana-source-structure-findings.md)
- [`docs/research/montana-gis-endpoints-verified.md`](../research/montana-gis-endpoints-verified.md)
- [`docs/research/colorado-draw-schema-proposal.md`](../research/colorado-draw-schema-proposal.md)
- [`docs/research/gmu-source-evaluation.md`](../research/gmu-source-evaluation.md)
