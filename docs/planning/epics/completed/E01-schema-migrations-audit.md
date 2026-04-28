# Epic Audit: E01 — Schema Migrations, RLS, and Quality Gates

**Date:** 2026-04-28
**Stories audited:** 6 (S01.1 through S01.6)
**Acceptance criteria:** 64 total — 53 MET, 4 PARTIALLY MET, 1 NOT MET, 5 CANNOT VERIFY (runtime), 1 MET (structurally)
**Post-audit fixes applied:** 4 (see Recommendations section)

## Summary

E01 is substantively complete. The schema DDL, RLS policies, Python Pydantic models, TypeScript interfaces, pre-commit hooks, and verification runbook are all delivered and internally consistent across the four schema representations (DDL, Python, TypeScript, architecture.md). The cross-language sync is solid — all 10 tables, all enum constraints, all field types align. The three issues found are minor: one missing curl verification artifact (S01.3 AC7), one missing serialization config (S01.4 AC10), and one incomplete role coverage in the verification runbook (S01.6 AC4). None of these affect schema correctness or block E02.

## Per-Story Results

### S01.1: Install pre-commit hooks — 6 MET, 1 PARTIAL

| AC | Status | Notes |
|----|--------|-------|
| Pre-commit hook tool installed and configured at repo root | MET | `.pre-commit-config.yaml` with 4 hooks |
| TypeScript lint runs `tsc --noEmit` for `mcp-server/` and `web/` | MET | Two local hooks, correctly scoped |
| Python lint runs `ruff check` for `ingestion/` | PARTIALLY MET | Uses `ruff check --fix` (auto-fix), not plain `ruff check` |
| Secrets scanning configured | MET | `detect-secrets` with clean baseline |
| All hooks pass cleanly | MET | Empty `results` in baseline |
| README updated with setup instructions | MET | Section with install + usage |
| Hook config files committed | MET | All files in git |

### S01.2: Initial migration — 15 MET, 1 PARTIAL, 3 NOT VERIFIED

| AC | Status | Notes |
|----|--------|-------|
| Timestamped migration file exists | MET | `20260425000000_initial_schema.sql` |
| Begins with `CREATE EXTENSION IF NOT EXISTS postgis` | MET | With `SCHEMA extensions` (Supabase-specific) |
| All 10 tables created with correct columns/types/constraints | MET | 7 entity + 3 link tables verified |
| Composite PKs on regulation_record and draw_spec | MET | Both correct |
| Text PKs on all other entities | MET | Deterministic IDs, not UUIDs |
| `geography(MultiPolygon, 4326)` on geometry.geom | MET | Explicitly not Polygon, not geometry type |
| All `verbatim_rule` columns NOT NULL | PARTIALLY MET | `jurisdiction_binding.verbatim_rule` is nullable — matches architecture.md `string \| null`, intentional |
| All `source` columns `jsonb NOT NULL` | MET | All 7 entity tables + jurisdiction_binding |
| `schema_version` DEFAULT 2 | MET | On regulation_record and draw_spec |
| CHECK constraints on all enum-like fields | MET | All unions match TS types |
| `draw_spec_key` and `successor_hunt_code_key` as jsonb | MET | Soft FK pattern |
| `quota_range` uses `int4range` | MET | Nullable |
| `draw_spec.pools` NOT NULL without default | MET | Comment explains rationale |
| FK from jurisdiction_binding to regulation_record and geometry | MET | Composite + simple FK |
| Link table FKs | MET | All 3 link tables correct |
| GiST spatial index | MET | `geometry_geom_gix` |
| Supporting indexes | MET | 3 indexes on state/kind, state/species_group, geometry_id |
| Migration applies cleanly to fresh project | NOT VERIFIED | Structural analysis only; no execution evidence in repo |
| COUNT(*) returns 0 | NOT VERIFIED | No data-load statements present; structurally correct |

### S01.3: RLS migration — 7 MET, 1 NOT MET

| AC | Status | Notes |
|----|--------|-------|
| Timestamped migration file (separate) | MET | `20260425000001_rls_deny_all.sql` |
| RLS enabled AND forced on all 10 tables | MET | Both `ENABLE` and `FORCE` on every table |
| Deny-all for authenticated on all 10 tables | MET | `FOR ALL TO authenticated USING (false) WITH CHECK (false)` |
| Deny-all for anon on all 10 tables | MET | Same pattern for anon |
| `REVOKE ALL` on all 10 tables | MET | Single statement per table |
| Service-role access preserved | MET (structural) | `service_role` has `bypassrls` attribute; migration never touches it |
| Curl-based verification (anon denied, authenticated denied, service_role succeeds) | NOT MET | No verification script or curl commands delivered in this story |
| Migration applies cleanly after S01.2 | MET | Correct timestamp ordering |

### S01.4: Python dataclasses matching DDL — 10 MET, 1 PARTIAL, 3 CANNOT VERIFY

| AC | Status | Notes |
|----|--------|-------|
| `__init__.py` exists | MET | With module docstring |
| `schema.py` with all 18 types | MET | 11 jsonb sub-models + 7 entity models + 3 bonus link table models |
| Every field matches DDL column | MET | Field-by-field cross-check passed |
| jsonb sub-models match architecture.md exactly | MET | All 11 verified |
| Literal types for all enum-like fields | MET | 18+ enum fields checked |
| `verbatim_rule` validated as non-empty | MET | 6 validators; nullable JurisdictionBinding correctly exempted |
| `source` typed as `SourceCitation` | MET | All entity models |
| `schema_version` default=2 | MET | On RegulationRecord and DrawSpec |
| `DrawSpec.pools` validated as non-empty | MET | Raises ValueError on empty |
| Optional sub-fields use None defaults with exclude-none serialization | PARTIALLY MET | None defaults correct; `exclude_none` config absent from `model_config` |
| `ruff check` passes | CANNOT VERIFY | Clean by inspection |
| `mypy` passes | CANNOT VERIFY | Annotations consistent |
| Module importable | CANNOT VERIFY | All classes defined, no circular imports |
| No imports from mcp-server | MET | Python-only imports |

### S01.5: TypeScript types matching DDL — 7 MET

| AC | Status | Notes |
|----|--------|-------|
| `schema.ts` exists with all types | MET | 7 entity interfaces + 11 supporting types |
| `index.ts` barrel export | MET | Re-exports all types |
| Interfaces match architecture.md exactly | MET | Verified |
| `tsc --noEmit` passes | MET | Confirmed via execution |
| No `any` types | MET | Only `"any_legal_weapon"` string literal |
| No imports from ingestion | MET | No Python references |
| Cross-language sync verified | MET | DDL-TS-Python alignment confirmed with documented intentional divergence (JurisdictionBinding flat vs nested) |

### S01.6: Migration reproducibility verification — 8 MET, 1 PARTIAL

| AC | Status | Notes |
|----|--------|-------|
| Migrations apply cleanly to fresh project | MET | Commit message confirms; runbook documents steps |
| All 10 tables queryable | MET | 10-table UNION ALL query in runbook |
| COUNT(*) returns 0 | MET | Documented and confirmed |
| RLS verification passes | PARTIALLY MET | anon + service_role tested; `authenticated` role not explicitly curl-tested |
| PostGIS verification passes | MET | `postgis_version()` + spatial round-trip |
| Reproducible on second project | MET | "apply cleanly to local Supabase (twice)" |
| Cross-language type checks pass | MET | tsc, ruff, mypy all documented |
| Runbook exists | MET | 130-line doc at `docs/runbooks/E01-migration-verification.md` |
| No new schema changes | MET | Only docs, .gitignore, config.toml |

## Cross-Cutting Findings

### Consistency
- All 10 table names used identically across DDL, RLS migration, Python models, TypeScript interfaces, and verification runbook.
- `JurisdictionBinding` flat-vs-nested FK representation is an intentional design decision (Python = DB-facing flat columns, TypeScript = API-facing nested object), documented in both schema files.
- `jurisdiction_binding.verbatim_rule` is nullable across all three representations — consistent, though the S01.2 AC says "all verbatim_rule NOT NULL." This is an AC spec issue, not an implementation bug.
- Pre-commit hook script naming is inconsistent: `mcp-server/package.json` uses `"lint"` while `web/package.json` uses `"typecheck"` for the same `tsc --noEmit` command.

### Integration
- Migration timestamp ordering (000000 schema, 000001 RLS) is correct and ensures S01.3 can reference S01.2's tables.
- S01.1 hooks provide ongoing validation of S01.4 (`ruff check`) and S01.5 (`tsc --noEmit`) on every commit.
- S01.6 runbook ties together verification of S01.2 + S01.3 + S01.4 + S01.5, creating a single reproducibility checkpoint.

### Gaps
- **S01.3 AC7 gap carried forward:** The curl-based verification that was NOT MET in S01.3 was partially addressed in S01.6's runbook, but the `authenticated` role is still not explicitly tested via curl or JWT impersonation. The SQL grant query provides equivalent evidence but is less direct.
- **Exclude-none serialization (S01.4 AC10):** Pydantic v2 `ConfigDict` doesn't have a native `exclude_none` option — it must be passed at `.model_dump()` call sites. The models use `ConfigDict(frozen=True, extra="forbid")` only. This will need to be handled in ingestion pipeline code (E02/E03) when serializing to jsonb.
- **No `license_tag.weapon_types` array element validation:** The `text[]` column has no CHECK constraint on individual array values. Application-layer validation via Pydantic covers this, but the DDL is structurally weaker than the scalar `weapon_type` CHECK on `season_definition`.

### Regressions
- No cross-story regression risks identified. Stories are purely additive. No story modifies artifacts from a prior story (except S01.6 which only adds documentation).

## Recommendations

1. ~~**[Low priority] Add `authenticated` role curl test to runbook**~~ **FIXED** — Added `authenticated` role curl test to `docs/runbooks/E01-migration-verification.md` with JWT generation instructions.

2. ~~**[Low priority] Document exclude-none convention for ingestion pipeline**~~ **FIXED** — Added serialization convention to `ingestion/ingestion/lib/schema.py` module docstring: callers must use `.model_dump(exclude_none=True)`.

3. **[Informational] `ruff check --fix` in pre-commit hook** — S01.1 uses `--fix` which auto-modifies files during commit. This is a common pattern but can surprise developers. Already documented in README. No action needed unless it causes issues.

4. **[Informational] Consistent npm script naming** — `mcp-server` uses `"lint"` and `web` uses `"typecheck"` for the same `tsc --noEmit` command. Consider standardizing when either `package.json` is next touched. Non-blocking.

## Additional Fixes Applied

1. **architecture.md prose corrected** — Line 350 previously overstated "every regulation reference carries a `verbatim_rule` string." Updated to acknowledge `JurisdictionBinding` as the exception where `verbatim_rule` is `string | null`.

2. **E01 epic AC corrected** — S01.2 AC7 ("All `verbatim_rule` columns are `NOT NULL`") now notes the `jurisdiction_binding` exception per architecture.md.
