# ADR-010: Decomposed Entity Model

**Date:** 2026-04
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** schema, storage

---

## Context

The v1 schema treated a regulation as a single `RegulationRecord` with embedded jurisdiction, applies_to, rules, and optional tag_info fields. First contact with Montana FWP's published regulations surfaced nine structural patterns the single-record shape could not express without duplication or ambiguity — multiple named seasons per hunting district, A-license and B-license splits with independent quotas, overlay geometries (Bear Management Units, CWD Management Zones) cross-cutting hunting districts, and six others enumerated in [`research/schema-v2-proposal.md`](../research/schema-v2-proposal.md). A single-table design could absorb these by cramming arrays into fields, duplicating records across seasons, or smuggling structure into free text, but each option degrades the schema's ability to answer queries without rederiving structure at read time.

## Decision

The regulation data model is decomposed into six entities — `regulation_record`, `season_definition`, `license_tag`, `draw_spec`, `reporting_obligation`, and geometry (`geometry` + `jurisdiction_binding`) — that compose to produce a regulation view. `regulation_record` is the anchor; the other entities are referenced by foreign key.

## Reasoning

The decomposition follows the real shape of the data. A hunting district with multiple seasons has a one-to-many relationship with seasons; a species with region-specific reporting has a one-to-many relationship with obligations. A normalized schema expresses these relationships; a denormalized schema hides them in JSON arrays or duplicated rows, forcing every query to rederive them.

Cross-sharing is the case that tips the decision. In Montana, a B license and its parent A license typically share season windows and jurisdiction bindings; an embedded design forces duplication across records that must stay in sync; a decomposed design lets both license_tags reference the same season_definition rows. Correcting a date updates one row, not an unknown number of copies.

This ADR commits to the entity count and the composition pattern, not to the exact field set of each entity. Field-level evolution is handled by the versioning commitment in [ADR-006](ADR-006-schema-versioned-from-day-one.md).

## Alternatives Considered

**Single `regulation_record` table with embedded JSON arrays for seasons, licenses, reporting, and geometries.** Simpler to query (one table, no joins). Rejected because the cross-sharing case produces duplication that must be kept in sync manually; because queries like "which HDs share this season window" become O(n) scans rather than joins; and because adding a seventh structural concern later — daily bag limits, for instance — means another embedded array rather than another table.

**Three entities instead of six: `regulation_record`, `tag_info`, `geometry`.** Rejected because collapsing seasons into `regulation_record` reproduces the original v1 failure mode, and collapsing reporting obligations into `tag_info` confuses permit mechanics with post-harvest duties — orthogonal concerns that vary independently and belong in different entities.

## Consequences

### Positive

- Each entity's lifecycle is legible: seasons, tags, and reporting evolve on their own cycles and are tracked independently.
- Cross-sharing (one season definition across multiple license tags) costs one join, not N duplicate rows.
- Adding a new regulatory concern in V2 — bag limits, drone restrictions, harvest quotas — is a new entity, not a reshaping of the existing one.

### Negative

- Six tables mean six migrations, six sets of indexes, and six foreign-key relationships to maintain. The setup cost is higher than a single-table design.
- Read queries require joins. Common queries (get all regulation detail for a jurisdiction) touch four or five tables; naive joins can produce Cartesian explosions if not written carefully.
- Three-place schema duplication (see [ADR-005](ADR-005-python-for-ingestion-typescript-for-serving.md) and [ADR-006](ADR-006-schema-versioned-from-day-one.md)) compounds across six entities rather than one; a schema_version bump touches more code.

### Neutral

- The response-shape decision ([ADR-011](ADR-011-shape-c-response-envelope.md)) is shaped around this model: the response envelope composes sections from the underlying entities rather than returning a single row.
- The draw-mechanics decision ([ADR-012](ADR-012-draw-mechanics-sibling-entity.md)) is a specific instance of this model's "sibling entity by foreign key" pattern.

## Links

- [`research/schema-v2-proposal.md`](../research/schema-v2-proposal.md) — The extended reasoning, including worked examples for Montana HD 262, BMU 411, and Colorado E-E-024.
- [ADR-006](ADR-006-schema-versioned-from-day-one.md) — Versioning makes the decomposition's field-level evolution safe.
- [ADR-011](ADR-011-shape-c-response-envelope.md) — The response shape composes from these entities.
- [ADR-012](ADR-012-draw-mechanics-sibling-entity.md) — A specific application of the sibling-entity pattern to draw mechanics.
