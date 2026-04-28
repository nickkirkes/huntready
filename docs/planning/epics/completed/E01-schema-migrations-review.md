# Epic Review: E01 — Schema Migrations, RLS, and Quality Gates

**Reviewer:** Ruckus epic-reviewer (Opus)
**Date:** 2026-04-24
**Verdict:** Ready (with minor revisions recommended)

---

## Summary

E01 is a well-structured, thorough epic that correctly translates the canonical schema from `architecture.md` and `schema-proposal-v2.md` into actionable implementation stories. The DDL specifications, RLS approach, and cross-language type mirroring are all technically sound. The epic correctly identifies three genuine ambiguities as escalation items. No blockers found that would prevent implementation. The findings below are improvements that reduce implementation friction, not structural problems.

---

## Findings by Dimension

### 1. Technical Accuracy

**1.1 `schema-proposal-v2.md` TypeScript interfaces are stale relative to `architecture.md` (S01.2, S01.5)**

The schema-proposal-v2 document still uses `draw_spec_id: string | null` and `successor_hunt_code: string | null`. The canonical `architecture.md` evolved these to `draw_spec_key: { state, hunt_code, year } | null` and `successor_hunt_code_key: { state, hunt_code, year } | null`. The epic's DDL correctly follows architecture.md (using jsonb soft FKs), but references *both* documents. **Recommendation:** Explicitly state in S01.2 context that architecture.md wins on any conflict with schema-proposal-v2.md.

**1.2 `season_definition.weapon_type` CHECK constraint is new DDL not in the reference (S01.2)**

The epic adds a CHECK constraint enumerating all 9 weapon types. The schema-proposal-v2 DDL has `weapon_type text` with no CHECK. This is a good enhancement aligning DDL enforcement with the TypeScript union. Intentional deviation — the AC correctly calls it out.

**1.3 `regulation_record.ingested_at` gets `DEFAULT now()` — sensible addition (S01.2)**

The epic specifies `DEFAULT now()` which schema-proposal-v2 DDL omits. Pragmatic improvement for ingestion — no issue.

**1.4 `ingestion/lib/` path question is real and correctly escalated (S01.4)**

The actual package structure is `ingestion/ingestion/`, and `pyproject.toml` declares `packages = ["ingestion"]`. The import path `from ingestion.lib.schema import ...` would require `lib/` to live at `ingestion/ingestion/lib/`, not `ingestion/lib/`. **This is a blocker for S01.4 and must be resolved before implementation.**

**1.5 `Geometry.geom` Pydantic type (S01.4)**

The deferral to implementer (WKT string vs GeoJSON dict) is appropriate. Shapely produces WKT natively and PostGIS accepts both.

**1.6 `reporting_obligation.kind` and `submission_method` CHECK constraints (S01.2)**

The epic correctly adds CHECK constraints missing from schema-proposal-v2 DDL. Good enhancement.

### 2. Best Practices

**2.1 RLS three-layer defense-in-depth is correct for Supabase (S01.3)** — ENABLE + FORCE RLS, deny-all policies, and explicit REVOKE is the correct pattern. Explanation of `service_role` `bypassrls` attribute is accurate.

**2.2 Separate migration files for schema and RLS is correct (S01.2, S01.3)** — Right pattern for independent adjustment later.

**2.3 `exclude_none=True` serialization convention is well-specified (S01.4)** — Correctly addresses the cross-language optional-field pitfall.

**2.4 Pre-commit hook story is appropriately flexible on tooling (S01.1)** — Deferring tool choice to implementer is correct for the polyglot structure.

### 3. Risks

**3.1 `source_date` escalation is the most urgent pre-implementation decision (Known Issue 1)**

CLAUDE.md and ADR-006 reference `source_date` on every row, but no canonical TypeScript interface has it — `publication_date` lives inside `source` jsonb. This is effectively a **pre-epic blocker**, not a mid-epic decision. The most likely resolution is that `source_date` was absorbed into `source.publication_date` during v1-to-v2 schema evolution and the prose was not updated. **Resolve before S01.2 starts.**

**3.2 `confidence` on child entities is documentation debt (Known Issue 2)**

Architecture.md prose says "Every entity carries a `confidence` field" but interfaces only place it on `RegulationRecord` and `VerbatimRule`. The epic follows the interfaces, which is correct. Lower urgency than `source_date`.

**3.3 S01.6 idempotency requirement may conflict with Supabase migration runner (S01.6)**

AC item "Re-applying migrations does not produce errors" — Supabase tracks applied migrations and won't re-apply them. This likely means "apply to a second fresh project," not "run twice on same database." Using `CREATE TABLE IF NOT EXISTS` would conflict with Supabase best practice. **Recommendation:** Clarify to mean "migrations apply cleanly to any fresh Supabase project."

**3.4 `tsc --noEmit` as pre-commit hook may be slow at scale (S01.1)**

Currently the projects are tiny so this is fine. As they grow, switching to `tsc --noEmit --incremental` or moving type-checking to CI may be needed. Non-issue for V1.

### 4. Overengineering

**4.1 No overengineering detected.** The 6-story structure maps directly to PRD E01 exit criteria. DDL specifications are detailed but necessarily so. RLS uses standard Supabase patterns. Cross-language sync is acknowledged as manual. Pre-commit hooks are a PRD deliverable.

**4.2 S01.4 specifies 18 types, which matches architecture.md exactly.** No invented types or unnecessary abstractions.

### 5. Acceptance Criteria Quality

**5.1 S01.2 ACs are the strongest — specific, testable, complete.** 19 criteria forming a comprehensive mechanical checklist.

**5.2 S01.1 "pass cleanly" could be more specific.** Does not clarify whether hooks should pass against pre-S01.1 or post-S01.1 state. Minor.

**5.3 S01.4 mypy parenthetical is overly cautious.** Pydantic 2.x ships with `py.typed` and full stubs, so `--ignore-missing-imports` should not be needed. Harmless.

**5.4 S01.6 AC "No new code changes" is ambiguous.** The story also delivers a runbook (a new document). **Recommendation:** Reword to "No new schema, migration, or type definition changes — this story only verifies existing work and produces documentation."

### 6. Dependencies

**6.1 Story ordering is correct and well-justified.** S01.1 → S01.2 → S01.3 → S01.4 → S01.5 → S01.6 follows logical dependency chain.

**6.2 S01.4 and S01.5 could theoretically run in parallel** (both depend on S01.2 but not each other). The sequential ordering is simpler and enables incremental cross-sync checking — a reasonable choice, not a mistake.

**6.3 Three known issues are correctly identified as pre-implementation blockers.** Known Issue 1 (`source_date`) and Known Issue 3 (`ingestion/lib/` path) are genuine blockers. Known Issue 2 (`confidence`) is lower priority but correctly flagged.

---

## Recommendations (prioritized by implementation impact)

1. **Resolve Known Issue 1 (`source_date`) and Known Issue 3 (`ingestion/lib/` path) before implementation begins.** For `source_date`, the likely resolution is that it was superseded by `source.publication_date` — update CLAUDE.md, ADR-006, and PRD prose. For `ingestion/lib/`, the correct path is almost certainly `ingestion/ingestion/lib/` given the existing `pyproject.toml`.

2. **Add a note to S01.2** that architecture.md is the canonical reference and wins on any conflict with schema-proposal-v2.md.

3. **Clarify S01.6 AC item 6** (re-apply migrations) to mean "apply to a second fresh project" rather than "run twice on the same database."

4. **Clarify S01.6 AC item 9** ("No new code changes") to explicitly permit documentation deliverables.

5. **Update architecture.md prose** regarding which entities carry `confidence` to align with the interfaces.
