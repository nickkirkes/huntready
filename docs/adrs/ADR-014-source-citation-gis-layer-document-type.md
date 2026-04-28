# ADR-014: SourceCitation `gis_layer` Document Type

**Date:** 2026-04
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** schema

---

## Context

`SourceCitation.document_type` currently enumerates four values — `annual_regulations`, `rule_change`, `emergency_order`, `correction` — and every value names a *published regulation document*. E02 introduces a new shape of source: ArcGIS MapServer feature services from Montana FWP (verified layers in [`docs/research/montana-gis-endpoints-verified.md`](../research/montana-gis-endpoints-verified.md)) that authoritatively publish polygon geometries. None of the existing values fit. Forcing `annual_regulations` would mean a query for "all annual_regulations sources" silently mixes GIS feature layers with PDF booklets, conflating two distinct provenance categories that downstream consumers need to distinguish.

## Decision

Extend `SourceCitation.document_type` with a fifth value, `gis_layer`, identifying citations whose source is an ArcGIS or comparable GIS feature service rather than a published regulation document. "Layer" here is the ArcGIS MapServer term for an addressable feature collection — not a Mapbox or UI overlay.

## Reasoning

The four existing values share a common shape: they describe regulation *documents* with a publication artifact, a `publication_date`, and prose-bearing pages. A GIS feature service is a different kind of authority — versioned by `REGYEAR`, queried via REST/WFS, and authoritative for *spatial* claims rather than textual rules. Naming it explicitly preserves the existing categories; collapsing it under `annual_regulations` damages them.

Enforcement stays at the type layer. Pydantic `Literal[...]` rejects unknown values at write time; the TypeScript union rejects them at compile time. The E01 DDL uses CHECK constraints freely for top-level enum columns (`geometry.kind`, `season_definition.weapon_types`, `regulation_record.confidence`, `jurisdiction_binding.role`); jsonb-internal enum keys, by contrast, are not CHECKed anywhere. Postgres *can* enforce them via `CHECK ((source->>'document_type') IN (...))`, but doing so just for `document_type` would mean propagating a parallel constraint across every table carrying a `source` column — substantial scope at V1 scale with no concrete drift to point at. The V1 posture is therefore explicit: top-level enum columns get SQL CHECK; jsonb-internal enum keys get type-layer enforcement. A future ADR can promote `document_type` to SQL CHECK if drift occurs.

Three-place sync ([ADR-006](ADR-006-schema-versioned-from-day-one.md)) follows the pattern E01 settled on: Pydantic, TypeScript, architecture.md. Because the SQL DDL does not encode this enum, no SQL migration accompanies the change; the architecture.md update is the audit trail.

`publication_date` for `gis_layer` citations is sourced from the ArcGIS feature's `REGYEAR` attribute (Jan 1 of `REGYEAR`) when present, and from the MapServer's published metadata otherwise. The field stays a date string per the existing contract — GIS sources do not get a special carrier — so consumers reading `publication_date` work uniformly across document types.

## Alternatives Considered

**Force `annual_regulations` for GIS sources.** Rejected: conflates a published booklet with a feature service; any future query filtering by document type silently returns mixed provenance, breaking the field's meaning.

**Make `document_type` a freeform string.** Rejected: the value is meaningful to downstream consumers (correction handling, MCP response composition); a freeform string lets each adapter invent its own variant and re-introduces the state-branching the enum prevents.

**Add a SQL CHECK constraint enforcing the enum.** Rejected for V1. The constraint would have to be applied uniformly to every entity table's `source` column, which is substantial scope for a category we have not yet seen drift in. Revisit if drift occurs.

## Consequences

### Positive

- GIS provenance can be cited without distortion. Downstream consumers can branch on `document_type === 'gis_layer'` cleanly for spatial-source-specific behavior.
- The change is minimal and additive — no SQL migration; three places plus the architecture.md interface block.

### Negative

- The change has no SQL audit trail; the architecture.md update is the only repo-level record. Drift between Pydantic and TypeScript would not be caught by Postgres at write time.
- One more enum value is one more case for downstream consumers to handle, including the corrections logic that already treats `correction` specially.

### Neutral

- This ADR commits HuntReady to type-layer-only enforcement of `source.document_type` for V1. A follow-on ADR can promote enforcement to a SQL CHECK constraint applied uniformly across every entity's `source` column if drift surfaces.

## Links

- [ADR-006](ADR-006-schema-versioned-from-day-one.md) — The three-place schema sync pattern this ADR follows.
- [ADR-008](ADR-008-verbatim-regulation-text.md) — The verbatim discipline; sibling ADR-015 carries verbatim regulatory text from `gis_layer`-typed sources.
- [ADR-015](ADR-015-geometry-verbatim-rule-and-reg-comments-handling.md) — The companion decision that adds `geometry.verbatim_rule` to carry the regulatory text these GIS-layer sources publish.
- [`docs/architecture.md`](../architecture.md) — § "Schema types" `SourceCitation` interface; updated alongside this ADR.
- [`docs/planning/epics/E02-geometry-ingestion.md`](../planning/epics/E02-geometry-ingestion.md) — § S02.0 originates this decision.
- [`docs/research/montana-gis-endpoints-verified.md`](../research/montana-gis-endpoints-verified.md) — The verified Montana GIS layers this enum value identifies.
