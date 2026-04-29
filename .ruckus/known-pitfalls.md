# Known Pitfalls

Project: huntready
Domain: Regulatory data platform for licensed hunting in the US.

Pitfalls discovered through development. Updated by `/ruckus:build` and `/ruckus:fix` wrap-up stages.

---

## Domain-Specific

<!-- Pitfalls related to the project's domain logic -->

## Data & State

<!-- Pitfalls related to data handling, state management, persistence -->

### `verbatim_rule` columns silently accept `""`

Both `JurisdictionBinding.verbatim_rule` and `Geometry.verbatim_rule` are nullable `text` with no SQL CHECK constraint and no Pydantic `@field_validator` to reject empty strings. An ingestion adapter that writes `verbatim_rule=""` will succeed silently, and downstream code using `if x.verbatim_rule:` cannot distinguish "no rule text in source" (intended `NULL`) from "empty rule text in source" (`""`).

**Why deferred:** Aligning the two columns is a cross-cutting fix (touches both E01 schema and E02 adapter writes); was out of scope for S02.0. Surfaced by silent-failure-hunter on 2026-04-28.

**Recommended cleanup when this becomes a real risk:** add a Pydantic validator that raises if `v is not None and not v.strip()` on both `Geometry.verbatim_rule` and `JurisdictionBinding.verbatim_rule`. Optionally add SQL `CHECK (verbatim_rule IS NULL OR length(verbatim_rule) > 0)` if a non-Python writer ever appears (none today; service-role bypass is a general risk, not specific to this column).

## Integration

<!-- Pitfalls related to APIs, third-party services, cross-system communication -->

## Build & Deploy

<!-- Pitfalls related to build process, CI/CD, deployment -->

### Style anchor for adding a nullable text column

When adding a nullable text column via a new migration, mirror `jurisdiction_binding.verbatim_rule` (`supabase/migrations/20260425000000_initial_schema.sql:207`) byte-for-byte:

- Type `text`, no `NOT NULL`, no default, no CHECK.
- Inline `--` comment on the same line documenting what `NULL` means semantically (e.g., `-- NULLABLE — null = no geometry-specific rule text from source attributes (REG/COMMENTS)`).
- No `COMMENT ON COLUMN` (E01 doesn't use it).
- For `ALTER TABLE` migrations, prefer `ADD COLUMN IF NOT EXISTS` — matches the `CREATE EXTENSION IF NOT EXISTS` idiom and makes the migration safely re-runnable on partially-applied environments.

The new column must also land in Pydantic (`ingestion/ingestion/lib/schema.py`) and TypeScript (`mcp-server/src/types/schema.ts`) in the same PR per ADR-006. Field ordering convention: nullable text fields go between `license_year` (or the last common field) and `source: SourceCitation`. Architecture.md §"Schema types" must also update — it's the audit trail for type-only enum extensions that have no SQL migration (per ADR-014).

## Testing

<!-- Pitfalls related to test reliability, test data, flaky tests -->
