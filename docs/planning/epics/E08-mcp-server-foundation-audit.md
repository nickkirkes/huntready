# Epic Audit: E08 — MCP Server Foundation

**Date:** 2026-06-30
**Auditor:** `roughly:audit-epic` (post-implementation, read-only; no source code modified)
**Epic:** [`E08-mcp-server-foundation.md`](E08-mcp-server-foundation.md)
**Stories audited:** 4 (S08.1, S08.2, S08.3, S08.4)
**Acceptance criteria:** 35 total — **at audit: 31 MET, 2 PARTIALLY MET, 0 NOT MET, 2 DEFERRED** (Group B, operator-pending by design). **The 2 PARTIALLY-MET S08.4 items were remediated same-day (2026-06-30) → 33 MET, 0 PARTIALLY MET** (see "Remediation" below).

> Method: each story reviewed by an independent per-story agent (sonnet) against its AC list and the merge-commit file set; cross-cutting consistency/integration/regression pass by the PM; quality gates re-run independently from the repo root.

---

## Summary

**E08 ships clean. 0 NOT MET, 0 blocking findings.** All four stories — the Streamable-HTTP Workers transport (S08.1), the read-only-enforced edge-Postgres access layer (S08.2), the Shape C response builder + reusable mechanisms (S08.3), and CORS + the wired-unenforced OAuth seam (S08.4) — meet their Group A acceptance criteria as merged. The two `PARTIALLY MET` items found at audit were both minor S08.4 test/documentation gaps (an integration-level preflight assertion under a restricted origin, and naming Cloudflare's ambient DDoS/WAF baseline in-source rather than only in ADR-023/CLAUDE.md); **both were remediated same-day** (see "Remediation") — neither was a functional defect. The two `DEFERRED` ACs are the Group B operator-pending live-deploy verifications (S08.1 Inspector connect; S08.2 live edge read + rejected write → the ADR-024 flip), correctly tracked as non-blocking.

**Independently re-verified quality gates (from repo root, 2026-06-30):**
- `tsc --noEmit` passes on **both** `tsconfig.json` (src) and `tsconfig.test.json` (tests) — strict mode, clean.
- Full vitest suite: **131 passed + 6 skipped = 137 total** at audit time — byte-matches the epic's claimed baseline (the 6 local-skips are the live-DB blocks that run in CI where `TEST_READONLY_DSN` is set); **133 + 6 = 139 after the same-day remediation** (+2 preflight tests).
- **No `any`** in serving `src/` (the lone grep hit is prose inside a `cors.ts` comment, not a type).
- **No `ingestion/` import** from `mcp-server/src/` (the two grep hits are doc-comment path references, not imports; AST guard in `boundary.test.ts` enforces this).
- **`schema.ts` zero-diff** — carries no response/envelope types; the three-place 6-entity sync was not touched (response types are serving-composition in `response.ts`, as designed).
- `.secrets.baseline` present; no DSN/token literal in any committed source.

The serving foundation E09/E10 build on is real and test-locked: per-request stateless transport, a single write-incapable read path with the Supabase WKT `ST_*` idiom baked in, an `architecture.md`-exact Shape C envelope with the `outputSchema`/gating/annotation mechanisms, and a pure-module/thin-shim router carrying CORS + the auth seam.

---

## Per-Story Results

### S08.1 — Server bootstrap + Streamable HTTP transport on Cloudflare Workers
**7/7 Group A MET · 1 DEFERRED (Group B).** No blocking findings.

| AC | Status | Evidence |
|----|--------|----------|
| #1 Worker `fetch` entrypoint via `createMcpHandler` (`agents/mcp`); per-request `createMcpServer()`; placeholder gone; call-site AST-locked | MET | `index.ts:47/71`; AST guard `boundary.test.ts:192-206` |
| #2 `initialize` conformant (compat date 2025-11-25); `protocolVersion` SDK-owned, not hardcoded; stateless | MET | `wrangler.jsonc:4`; `server.test.ts:68-74`; no-`protocolVersion` AST guard `boundary.test.ts:216-219` |
| #3 `tools/list` empty array; `tools` capability declared; register-then-remove idiom; registry locked empty | MET | `server.ts:27-35,50-53`; `server.test.ts:77-119` |
| #4 `wrangler.jsonc` committed, no DO binding/migration; `@cloudflare/workers-types` wired; scripts; tsc strict; no `any` | MET | no `durable_objects`/`migrations` keys; `tsconfig.json:8`; no-DO lock `boundary.test.ts:147-155` |
| #5 vitest harness + `test`/`test:ci` + first CI workflow; baseline 15 (6+9) | MET | `package.json:11-12`; `ci.yml`; 15-test count verified at merge `0361a65` |
| #6 `mcp-remote` local-dev path documented in README (note, no stub) | MET | `README.md:18-25` |
| #7 no `ingestion/` import; no Python required | MET | AST guard `boundary.test.ts:165-182` |
| #8 Deploy to Workers preview + MCP Inspector connect | DEFERRED | Group B, operator-pending (`README.md:29-30`) — by design, non-blocking |

### S08.2 — Edge-Postgres driver spike + read-only-enforced access layer
**9/9 Group A MET · 1 DEFERRED (Group B).** No blocking findings.

| AC | Status | Evidence |
|----|--------|----------|
| #1 Spike → postgres.js direct; `@neondatabase` ruled out; Hyperdrive deferred; rationale in working note | MET | `S08.2.md §1`; `db.ts:27` |
| #2 Connect-per-request, `max:1`, no cross-request pool; workerd socket posture recorded | MET | `db.ts:90,93`; `S08.2.md §2` |
| #3 `src/db.ts` single read path; `READ_SMOKE_SQL` + `ST_VALID_SMOKE_SQL` WKT round-trip exported; no PostgREST | MET | `db.ts:143-161` (WKT idiom literal at :161) |
| #4 SELECT-only DSN; `grant-readonly-role.sql` committed; INSERT/UPDATE/DELETE rejected at SQLSTATE 42501 vs real GRANT (not a mock) | MET | `db.test.ts:116/125/150`; `grant-readonly-role.sql` |
| #5 CI PostGIS substrate (`postgis/postgis:16-3.4` + `ci-substrate.sql` + GRANT) closes role-level + ST_* ACs in CI | MET | `ci.yml:17,43-48`; `ci-substrate.sql` (relocates PostGIS to `extensions`) |
| #6 DSN as Workers Secret (`SUPABASE_READONLY_DSN`); name documented, literal never; `.dev.vars` gitignored; baseline preserved | MET | `index.ts:11`; `wrangler.jsonc:21`; `.gitignore:1-2` |
| #7 Hyperdrive-caching AC N/A (not chosen); recorded as drop-in | MET | `S08.2.md §4` |
| #8 Q14 finding: Supavisor transaction-pooler DSN format; advances serving half (not closed) | MET | `S08.2.md §3` |
| #9 tsc strict; no `any`; no `ingestion/` import | MET | documented double-cast `db.ts:111-117`; AST guard green |
| #10 Live edge read + provably-rejected write from deployed Worker | DEFERRED | Group B — gates ADR-024 `Proposed → Accepted` (`S08.2.md §6`) |

### S08.3 — Shape C response builder + envelope/section types + reusable mechanisms
**8/8 MET.** No Group A/B split. **`architecture.md` §"Response shape" conformance verified field-by-field — exact, zero divergences.**

| AC | Status | Evidence |
|----|--------|----------|
| #1 Full contract in separate `response.ts` (schema.ts zero-diff); matches `architecture.md` exactly (nullable `resolved.jurisdiction`, `ResolvedTag.draw_spec: DrawSpec\|null` + `reserved_pools`, 7-value `Warning.code`, `meta.schema_version:2`, >180d `is_stale`); tsc strict; no `any` | MET | `response.ts:24-158`; `response-builder.ts:183`; compile-time `AssertEqual`/`SameKeys` drift-guards in `output-schema.ts` |
| #2 Round-trip fixture: explicit-null sections; no-data(null+`"none"`) vs not-required(`[]`+`"full"`); all 3 Coverage values; stale+fresh `is_stale`; `sources[]` present | MET | `response.test.ts:111-302` |
| #3 `structuredContent`+`outputSchema`+read-only annotations reusable helper; server-side validation; **negative test** rejects schema-violating payload | MET | `response-builder.ts:31,284-304`; negatives `response.test.ts:319-363` |
| #4 schema-version gating: excluded + `UNSUPPORTED_SCHEMA_VERSION`/`section:"overall"` warning naming version; synthetic out-of-range test | MET | `response-builder.ts:209-229`; `response.test.ts:370-407` (v999) |
| #5 no `overview`/`headline`; thin `content[0].text`; `verbatim_rule` bytes + non-high `confidence` pass through unchanged | MET | `response-builder.ts:245-267`; `response.test.ts:413-451` (soft-hyphen byte-identity; confidence `"medium"`) |
| #6 `/healthz` exercises envelope + real DB read; NOT a registered MCP tool (`tools/list` unchanged) | MET | `health-check.ts`; `router.ts:90`; not via `registerTool` |
| #7 barrel-export convention decided + applied in `types/index.ts` | MET | `types/index.ts:25-38`; AST lock `boundary.test.ts:285-294` |
| #8 no `ingestion/` import; no `any` | MET | AST guard `boundary.test.ts:165-182` |

*Flagged (not a defect): `output-schema.ts` enforces `sources.min(1)` while `architecture.md` declares `sources: SourceCitation[]` (allows empty). Already escalated in-code (`output-schema.ts:507-513`) and in CLAUDE.md as a 🚩 SPEC-CANDIDATE requiring a human decision before E09's `get_regulations` (first zero-source-capable tool). Surfaced, not silent.*

### S08.4 — CORS/preflight + OAuth-2.1 auth seam (wired, unenforced) + boundary guards
**At audit: 3 MET · 2 PARTIALLY MET → 5 MET after same-day remediation.** No Group A/B split. No blocking findings.

| AC | Status | Evidence |
|----|--------|----------|
| #1 CORS headers + `OPTIONS` preflight; configurable allowed-origin (`CORS_ALLOWED_ORIGINS`, permissive default); preflight test | MET *(remediated 2026-06-30)* | Logic fully present + unit-tested (`cors.ts:90-158`, `router.ts:79-87`). At audit: PARTIALLY MET — no integration-dispatch test asserted an echoed **restricted** origin in the 204. **Remediation:** `router.test.ts` +2 tests — a preflight from a configured restricted origin asserts the echoed (non-`*`) origin + `Vary: Origin` in the 204, and a non-allowlisted preflight asserts `Access-Control-Allow-Origin` omitted. |
| #2 Single config-toggled seam; enabled→401 with RFC 9728 `WWW-Authenticate` (not bare token compare) + credentialed admitted; deployed V1 disabled; fixture-not-boundary documented; `workers-oauth-provider` named drop-in | MET | `router.ts:98-103`; `auth.ts:52-56,130-163` (fail-closed); default-disabled (`wrangler.jsonc:48-54`); `router.test.ts:173-197`, `auth.test.ts` |
| #3 Seam credential from Workers Secrets, never committed; baseline preserved | MET | `wrangler.jsonc:56-64`; test tokens carry `# pragma: allowlist secret` |
| #4 Mechanical no-`ingestion/`-import guard; tsc strict, no `any` | MET | AST guard `boundary.test.ts:165-182`; `tsconfig.json:8` |
| #5 Q22 referenced as deferred; Cloudflare ambient DDoS/WAF named as V1 baseline | MET *(remediated 2026-06-30)* | Q22 deferral named in `auth.ts:19-24`, `index.ts:32-34`, `wrangler.jsonc:48-54`. At audit: the DDoS/WAF baseline lived only in ADR-023 + CLAUDE.md. **Remediation:** `auth.ts` module docstring now carries a "V1 BASELINE PROTECTION" block naming Cloudflare's ambient DDoS mitigation + WAF as the platform-default baseline (and re-pointing enforced metering to Q22/V2). |

---

## Cross-Cutting Findings

- **Consistency — strong.** The pure-module + thin-shim architecture (`cors`/`auth`/`router` importing no `agents/mcp`; `index.ts` a minimal Worker shim with the per-request `createMcpServer()` lock preserved inside the injected callback) is applied uniformly and is the routing/middleware pattern E09/E10 inherit. Boundary guards are AST-based (the TS analog of the Python `ast.walk` guards), grown additively across stories — the original S08.1 tests remain present and unmodified after S08.2/S08.3/S08.4 extended the file.
- **Integration — clean.** `index.ts` legitimately evolved S08.1 (entrypoint) → S08.2 (DSN wiring) → S08.3 (`/healthz`) → S08.4 (router shim). The end-to-end suite (131+6) passes against the integrated tree; no story's change broke a prior story's locked behavior. The `/healthz`-before-auth-seam ordering (S08.4 fix) correctly resolved a latent P1 where both paths read the single `Authorization` header expecting different tokens.
- **Gaps — two at audit, both minor and confined to S08.4 (above), both remediated same-day.** No AC is left without an implementing story; the only schema-layer escalation (S08.3 `sources.min(1)` vs nullable `data_freshness`) is properly surfaced as a human decision, not a silent divergence.
- **Regressions — none detected.** Full suite green; schema.ts/migrations/ingestion/web zero-diff held across all four merges.

---

## Recommendations

1. **✅ DONE (2026-06-30) — (Low · test) S08.4 AC1 integration-level preflight assertion.** `router.test.ts` now has a `handleRequest` preflight test with `CORS_ALLOWED_ORIGINS` set to a restricted origin asserting the 204 echoes that origin (not `*`) + `Vary: Origin`, plus a non-allowlisted preflight asserting the header is omitted. No story reopened.
2. **✅ DONE (2026-06-30) — (Low · doc) S08.4 AC5 name the DDoS/WAF baseline in-source.** `auth.ts` module docstring now names Cloudflare's ambient DDoS/WAF as the V1 baseline protection where the seam lives.
3. **(Tracked · non-blocking) Group B operator verifications remain open.** S08.1 (deploy + MCP Inspector connect) and S08.2 (live edge read + provably-rejected write) are operator-pending. S08.2 Group B is the gate that flips **ADR-024 `Proposed → Accepted`** (PM flags; human edits the ADR). Capture in the E08 working note, then tick the Group B ACs in a follow-up doc-only commit.
4. **(Human decision before E09) S08.3 spec-candidate.** Resolve `sources.min(1)` vs nullable `meta.data_freshness` in `architecture.md` §"Response shape" before `get_regulations` (the first zero-source-capable tool). This is one of the three pre-registered E09-entry decisions in the epic close-out.
5. **(Consider in E09) Single-read-path guard.** Per the epic's forward note, consider a lint/test guard that `src/db.ts` is the only module opening a DB connection — the serving analog of the no-`ingestion/`-import guard, cheap insurance against an uncontrolled second query path (the thing ADR-004 exists to prevent).

---

## Remediation (2026-06-30, same-day)

Recommendations 1 and 2 (the two PARTIALLY-MET S08.4 items) were applied immediately; the rest are operator-pending (Group B), a human decision (S08.3 spec-candidate), or an E09 consideration, and were not actioned here.

- **Rec 1 (S08.4 AC1) — done.** `mcp-server/tests/router.test.ts` gains two integration-dispatch preflight tests: an `OPTIONS` preflight from a configured restricted origin asserts the echoed non-`*` origin + `Vary: Origin` in the 204 and that the MCP handler is not invoked; a non-allowlisted preflight asserts `Access-Control-Allow-Origin` is omitted. `router.test.ts` 13 → 15.
- **Rec 2 (S08.4 AC5) — done.** `mcp-server/src/auth.ts` module docstring adds a "V1 BASELINE PROTECTION" block naming Cloudflare's ambient DDoS mitigation + WAF as the V1 platform-default baseline, with enforced metering re-pointed to Q22/V2.
- **Verification:** `tsc --noEmit` clean on both configs; full vitest suite **133 passed + 6 skipped = 139** (was 131 + 6 = 137; +2 additive, no regressions).
- **Not actioned (by design):** Rec 3 (Group B operator verifications — S08.1 deploy/Inspector, S08.2 live read → ADR-024 flip); Rec 4 (S08.3 `sources.min(1)` vs nullable `data_freshness` — human decision before E09); Rec 5 (single-read-path guard — E09 consideration).

---

## Verdict

**E08 — MCP Server Foundation is sound and may close its audit gate.** All Group A acceptance criteria across the four stories are MET; the two PARTIALLY MET items are minor S08.4 test/doc gaps with named remediations; the two DEFERRED items are correctly-tracked Group B operator verifications. Independently re-run quality gates (tsc strict ×2, 131+6 tests, no `any`, no `ingestion/` import, schema.ts zero-diff) corroborate the closure record. No blocking findings — **0 NOT MET**.

Per the project's post-implementation-audit standard, this satisfies the `Audited:` gate for E08; `/plan-next-epic` for E09 may proceed once this audit lands **and** the three E09-entry decisions in the epic close-out are resolved (the S08.3 `sources` spec-candidate; the empty-`tools/list` keep-vs-relax call; the `gateBySchemaVersion`-warning-wiring guard).
