# ADR-012: Draw Mechanics as Sibling Entity

**Date:** 2026-04
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** schema

---

## Context

Limited-draw tag lotteries allocate high-demand hunting permits in most Western states, and the mechanics vary widely — point systems, selection algorithms, residency allocations, and eligibility predicates differ materially between Colorado, Wyoming, New Mexico, and Utah (the V1-candidate states surveyed in [`research/colorado-draw-schema-proposal.md`](../research/colorado-draw-schema-proposal.md)).

A schema that special-cases each state — with `colorado_draw`, `wyoming_draw`, and `nm_draw` columns or tables — fails the operating principle that shared code must not branch on state. State adapters are allowed to contain state-specific logic; the MCP server's `get_tag_requirements` tool is not.

## Decision

Draw mechanics are modeled as a sibling entity `draw_spec` with composite primary key `(state, hunt_code, year)`, referenced from `license_tag` by foreign key. The entity composes a `point_system` (null for no-points states), a `residency_cap`, a `choices` config, and an `allocation_pool[]` array where each pool has a share (0.0–1.0), an enumerated selection algorithm, and an eligibility predicate. State-specific metadata lives in a typed `parameters` field that shared code never reads.

## Reasoning

The variation across states lives in two axes: the point system (none, preference-linear, bonus-squared, bonus-weighted) and the selection algorithm per pool (rank-ordered, unweighted random, squared-weighted random, linear-weighted random). Both axes are finite enumerations observed across all four V1-candidate states. Everything else — who is eligible for which pool, what share each pool gets, whether there is a minimum point threshold — is a value, not a structural feature.

The Colorado proposal verified this generalization by representing all four V1-candidate states' 2026 rules as `draw_spec` records with no state-specific fields. Colorado's hybrid-eligible elk unit serializes as two pools (80% rank-ordered, 20% unweighted-random with min_points=5). Wyoming and New Mexico serialize with different pool counts, selection algorithms, and eligibility predicates — but the same column set; Utah's squared-bonus mechanic is accommodated by adding one value to the selection enum. Shared code — the `get_tag_requirements` tool, the response builder — branches on `point_system.kind` and `pool.selection`, never on `state`.

The `parameters` escape hatch is typed as `Record<string, unknown>` and the discipline — enforced by convention and code review — is that shared code never reads it. State adapters use it for metadata that does not affect the draw mechanics the schema models: Wyoming tier pricing, Utah youth allocation categories, Colorado's moose exponential-weighting formula.

## Alternatives Considered

**Flat fields on `license_tag` (draw_algorithm, preference_point_share, min_points_threshold, nonresident_cap).** Rejected because the null density becomes meaningful: a `null` in `preference_point_share` ambiguously means "100% preference points" (Colorado non-hybrid) or "no points system" (New Mexico). Multiple allocation pools per tag cannot be represented without parallel arrays.

**`jsonb` blob without a structured contract.** Rejected because it offers flexibility without query power — the MCP server cannot efficiently answer "which hunt codes require ≥5 points" without scanning every row — and because an unstructured blob lets each state adapter invent its own shape, which directly violates the no-state-branches constraint.

## Consequences

### Positive

- Four states' draw mechanics share one schema, verified against real 2026 rules. V2 state onboarding is adapter work, not schema work.
- The `pools[]` structure accommodates reserved sub-pools (landowner preference in Montana, youth allocation in Utah) as additional pool entries without schema extension.
- Annual updates are a new row with a new `year`, not an overwrite; history is preserved.

### Negative

- `pools` and `point_system` are stored as `jsonb` for write ergonomics, not as normalized child tables; Postgres cannot enforce share-sum-to-1.0 or pool-eligibility consistency as constraints. Validation runs in application code.
- `parameters` is a loaded gun. Type-level enforcement of "shared code does not read this" is impossible in TypeScript; the discipline is social, and a single shared module that reads `parameters` would silently violate the no-state-branches constraint.

### Neutral

- This ADR is the specific instance of the sibling-entity pattern committed in [ADR-010](ADR-010-decomposed-entity-model.md). Future sibling entities (bag limits, access overlays) should follow the same composite-key and `parameters`-escape-hatch conventions for consistency.

## Links

- [ADR-010](ADR-010-decomposed-entity-model.md) — The sibling-entity pattern this ADR applies.
- [ADR-011](ADR-011-shape-c-response-envelope.md) — `draw_spec` is embedded in the response envelope's `ResolvedTag`.
- [`research/colorado-draw-schema-proposal.md`](../research/colorado-draw-schema-proposal.md) — Extended reasoning, state comparisons, and worked examples.
- [`research/schema-proposal-v2.md`](../research/schema-proposal-v2.md) — The entity in its schema context.
