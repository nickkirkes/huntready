# ADR-015: Geometry Verbatim Rule and REG+COMMENTS Handling

**Date:** 2026-04
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** schema

---

## Context

Montana FWP MapServer publishes verbatim regulatory text on the polygon-bearing layers E02 ingests: layer #2 (Big Game Restricted Areas) carries `REG` and `COMMENTS`, layer #11 (Deer Elk Lion Hunting Districts) carries `REG`, and layer #14 (Elk Portions) carries both. These fields hold polygon-scoped regulation prose — for example, weapon constraints inside a specific restricted area. Verified field inventory: [`docs/research/montana-gis-endpoints-verified.md`](../research/montana-gis-endpoints-verified.md).

Per [ADR-008](ADR-008-verbatim-regulation-text.md), this text must be preserved verbatim. The current `geometry` table has no place for it: `source` jsonb is provenance, and the [ADR-008](ADR-008-verbatim-regulation-text.md) boundary forbids mixing regulatory text into provenance; `jurisdiction_binding.verbatim_rule` is nullable but depends on `regulation_record` rows that do not exist until E03. Layers #2 and #14 add a second decision: two verbatim source attributes must collapse into a single column, and the combination rule needs to be explicit rather than an implicit choice in a Python helper.

## Decision

Add `verbatim_rule text` (nullable) to the `geometry` table, mirrored in Pydantic `Geometry.verbatim_rule: str | None = None` and TypeScript `Geometry.verbatim_rule: string | null`. Define a five-case rule for combining ArcGIS `REG` and `COMMENTS` into the column, using a HuntReady-introduced separator `\n\n--- COMMENTS ---\n\n` when both fields are populated and differ.

## Reasoning

The column is nullable because not every geometry has source-side text. Layer #11 always carries `REG`; layer #2 mixes populated and empty; hand-traced CWD overlays land with `NULL`. NOT NULL would force fabricated values. The `string | null` shape matches `JurisdictionBinding.verbatim_rule`, the only other nullable `verbatim_rule` in the schema.

The five-case combination rule:

| `REG`            | `COMMENTS`                          | `verbatim_rule` value                         |
| ---------------- | ----------------------------------- | --------------------------------------------- |
| populated        | populated, **different** from `REG` | `f"{REG}\n\n--- COMMENTS ---\n\n{COMMENTS}"`  |
| populated        | populated, **identical** to `REG`   | `REG` (do not double-store)                   |
| populated        | empty/whitespace                    | `REG`                                         |
| empty/whitespace | populated                           | `COMMENTS`                                    |
| empty/whitespace | empty/whitespace                    | `NULL`                                        |

The separator `\n\n--- COMMENTS ---\n\n` is a deliberate editorial choice. Pure `\n\n` concatenation was rejected because it loses the signal that the two halves came from distinct source attributes — a signal future consumers (E03 binding logic, MCP response composition that may want to surface `COMMENTS` separately) need. [ADR-008](ADR-008-verbatim-regulation-text.md)'s verbatim discipline is preserved because **the source strings themselves are not modified** — only their concatenation is annotated. The verbatim guarantee holds on the strings, which round-trip exactly; the annotation is provenance metadata, not paraphrase.

**The separator string is frozen, not stylistic.** Implementations must use the literal token `\n\n--- COMMENTS ---\n\n` byte-for-byte; do not localize it, prettify it, or substitute a different delimiter. The token is a contract that downstream consumers split on. Edge case: if a future `REG` or `COMMENTS` value contains the literal substring `--- COMMENTS ---` (not yet observed in MT FWP data), the round-trip property breaks; escalate via `open-questions.md` rather than silently re-encoding.

The combination logic lives in the Montana state adapter (`ingestion/states/montana/`), not shared `ingestion/ingestion/lib/`, because which fields exist on which layer is a property of the FWP MapServer schema, not of HuntReady. If a future state has a comparable two-field shape, the rule lifts into shared code at that point.

## Alternatives Considered

**A second column `verbatim_comments text`.** Rejected: forces a schema-level decision about which is primary, and consumers walking the response still handle both. The single-column shape matches every other `verbatim_rule` in the schema.

**Encode as JSON `{"reg": ..., "comments": ...}`.** Rejected: every read site would decode, and verbatim text is consumed as prose by the MCP response composer and the web disclosure panels.

**Store the verbatim text in `source` jsonb.** Rejected: conflates provenance with regulation text — the exact boundary [ADR-008](ADR-008-verbatim-regulation-text.md) draws.

**Defer to E03's `jurisdiction_binding.verbatim_rule`.** Rejected: binding rows do not exist in E02, so deferral loses the text at ingestion time and forces a re-fetch. The binding's `verbatim_rule` is also semantically different — binding-specific text scoped to a relationship, not the geometry.

## Consequences

### Positive

- Source-side verbatim regulatory text is captured at the layer hardest to lose ([ADR-008](ADR-008-verbatim-regulation-text.md)) — ingestion time, into a stable column.
- The five-case rule is fully specified; the Montana adapter's combination logic is reviewable against a contract.
- The `string | null` shape mirrors `JurisdictionBinding.verbatim_rule`, so consumers handling either column use one pattern.

### Negative

- The HuntReady-introduced separator is editorial. Consumers must know the literal token `--- COMMENTS ---` is HuntReady's annotation, not source content. The verbatim guarantee holds on the source strings themselves; the *string carrier* now mixes source content with HuntReady annotation, which is an honest cost.
- The combination rule lives in the Montana adapter; if a future state has a comparable two-field shape, lifting to shared code re-litigates the layer-specific assumption.
- This ADR does not decide whether the literal `--- COMMENTS ---` token reaches user-facing surfaces. Per [ADR-013](ADR-013-server-returns-structure-client-composes-presentation.md), presentation belongs to clients; whether the MCP response composer or web disclosure panel splits on the separator, renders both halves with distinct labels, or surfaces the raw string is a downstream decision. Open question for E03/composer work, not resolved here.

### Neutral

- Three-place sync ([ADR-006](ADR-006-schema-versioned-from-day-one.md)) applies: SQL migration adds the column; Pydantic gains `verbatim_rule: str | None = None`; the TypeScript `Geometry` gains `verbatim_rule: string | null`; architecture.md updates the interface. Standard versioning cost.

## Links

- [ADR-006](ADR-006-schema-versioned-from-day-one.md) — Schema-versioning posture; this change is a migration plus three-place sync.
- [ADR-008](ADR-008-verbatim-regulation-text.md) — The verbatim discipline this ADR carries to the geometry layer.
- [ADR-010](ADR-010-decomposed-entity-model.md) — The entity model in which `geometry` and `jurisdiction_binding` live; the latter's `verbatim_rule` is the precedent this column follows.
- [ADR-014](ADR-014-source-citation-gis-layer-document-type.md) — Sibling decision; together they enable GIS-layer geometries to land with both correct provenance and verbatim regulatory text.
- [`docs/planning/epics/E02-geometry-ingestion.md`](../planning/epics/E02-geometry-ingestion.md) — § S02.0 + § S02.4 originate this decision.
- [`docs/research/montana-gis-endpoints-verified.md`](../research/montana-gis-endpoints-verified.md) — Source field inventory for layers 2, 11, 14.
