# ADR-006: Schema Versioned From Day One

**Date:** 2026-04
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** schema

---

## Context

State hunting regulations change annually (most states publish between March and July), and the schema for how HuntReady *models* regulations will change as states and species land. Two kinds of change are known. Content drift — every record has a `source_date` and an annual successor. Structural drift — the Montana research cycle surfaced nine schema pressure points that moved the schema from v1 to v2 before V1 even shipped, and a third round is likely during M1/M2 as real data confronts the schema.

A schema that does not anticipate its own evolution tends to acquire silent misinterpretations: a v2 reader reads a v1 record, assumes fields that aren't there, and produces a wrong answer confidently.

## Decision

Every regulation record carries an explicit `schema_version` column, every schema change is captured as an ordered Postgres migration, and the MCP server rejects records whose `schema_version` it does not support rather than silently misinterpreting them.

## Reasoning

Schema versioning from day one turns schema evolution from a crisis into an expected event. The MCP server has a known set of supported `schema_version` values at any given time; records outside that set produce a structured "not supported" response, never a subtly-wrong one. A v2 reader cannot mistake a v1 row for a v2 row, and vice versa. The failure mode is loud, which is what a regulation product needs.

**M3 serving realization (2026-06-26).** This "reject, don't misinterpret" rule is realized in the serving layer (M3/E08) as **exclude-and-surface**, not a hard error: a row whose `schema_version` is outside the server's supported set is excluded from tool output and flagged in `meta.warnings` with `code: "UNSUPPORTED_SCHEMA_VERSION"` (the 7th value added to the `Warning` union in [`architecture.md`](../architecture.md) §"Response shape" per [ADR-011](ADR-011-shape-c-response-envelope.md)). This reconciles this ADR's loud-failure intent with the "never silent empty" principle of Shape C — the unsupported row is neither silently dropped nor allowed to hard-error the whole response.

Migrations live in `supabase/migrations/` as timestamped SQL files and are the single place where structural changes are recorded. Every schema change is a migration — including additions Postgres would otherwise accept without one — so the ordered file list is a readable history of the schema's evolution. A v1-to-v2 migration is an anticipated event; v2-to-v3 will be no different.

The V1 evidence is concrete: the schema moved from v1 to v2 before any data was loaded, driven by nine structural patterns surfaced in Montana's published regulations (captured in [ADR-010](ADR-010-decomposed-entity-model.md)). A correction PDF for Montana's 2026 Black Bear regulations was published 2026-03-18, the day after the base booklet, amending hound-hunting language and removing a column from the BMU table. Corrections are routine, and the schema needs a `document_type: "correction"` value and a `supersedes` pointer so corrections are modeled, not applied in-place. An unversioned schema would make retroactively adding either a risky change; a versioned schema makes it a v2-to-v3 migration with clear semantics.

## Consequences

### Positive

- Schema change is a planned event, not a breakage. New versions do not silently misinterpret old rows.
- The migration history is the schema's history; reviewers read it top to bottom.
- `schema_version` gives the response envelope a natural place to signal data provenance.

### Negative

- Every schema change has two representations (the Postgres migration and the `schema_version` bump) and a decision about whether older rows are back-migrated or left on their old version, neither answer being free.
- The MCP server must carry the complexity of supporting multiple concurrent `schema_version` values during transitions, or do a hard cutover that temporarily invalidates old rows.
- Three-place schema duplication (see [ADR-005](ADR-005-python-for-ingestion-typescript-for-serving.md)) compounds the versioning burden; a bump propagates to three files and their test suites.

### Neutral

- This ADR commits HuntReady to treating its data model as an evolving artifact with a public contract, which shapes how later decisions — especially a B2B API in V2 — are structured around version negotiation.

## Links

- [ADR-004](ADR-004-supabase-postgres-postgis.md) — Migrations live in Supabase's migration directory.
- [ADR-005](ADR-005-python-for-ingestion-typescript-for-serving.md) — The three-place schema duplication that makes versioning more work.
- [ADR-008](ADR-008-verbatim-regulation-text.md) — Verbatim text is part of the schema contract that evolves under versioning.
- [ADR-010](ADR-010-decomposed-entity-model.md) — The v1-to-v2 structural revision; the first real exercise of this ADR's versioning commitment.
- [ADR-011](ADR-011-shape-c-response-envelope.md) — The Shape C envelope whose `Warning` union carries `UNSUPPORTED_SCHEMA_VERSION`, the serving realization of this ADR's gating rule.
- [`docs/architecture.md`](../architecture.md) §"Response shape" — the `Warning` union (7th value `UNSUPPORTED_SCHEMA_VERSION`) and `meta.warnings`.
- [`docs/research/schema-proposal-v2.md`](../research/schema-proposal-v2.md) — The v1-to-v2 reasoning already executed before V1.
