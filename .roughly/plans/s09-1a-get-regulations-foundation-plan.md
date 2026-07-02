> **Status:** Historical — implemented and merged in commit bd33728d2186291132eef25e10c7d1535ba7f36d on 2026-07-01. This plan was an active build/fix artifact; treat as historical reference only.

# Implementation Plan: S09.1a — `get_regulations` foundation

Plan-format-version: 1

Scope: the `[1a]`-tagged ACs of E09 story S09.1 only. Touches only `mcp-server/`.
Foundation for `get_regulations`; the full composite rigor (edge cases, ≤N-query bound,
coverage tri-state boundaries, `verbatim_rule`/`confidence`/`additional_rules` byte-identity,
no-silent-authority-loss guard) is S09.1b — a SEPARATE future PR and explicitly OUT of scope here.

Baseline before this work: 133 passed + 6 skipped (local) / 139 (CI). Grow additively.

## File Table
| File | Action | Task(s) |
|------|--------|---------|
| mcp-server/src/types/response.ts | Modify | T1 |
| mcp-server/src/types/index.ts | Modify | T1 |
| mcp-server/src/output-schema.ts | Modify | T2 |
| mcp-server/src/response-builder.ts | Modify | T3 |
| mcp-server/src/tools/get-regulations.ts | Create | T4 |
| mcp-server/src/server.ts | Modify | T5 |
| mcp-server/src/health-check.ts | Modify | T6 |
| mcp-server/tests/server.test.ts | Modify | T7 |
| mcp-server/tests/response.test.ts | Modify | T8 |
| mcp-server/tests/boundary.test.ts | Modify | T9 |
| mcp-server/tests/get-regulations.test.ts | Create | T10 |

## Tasks

### T1: Decision 1 + `additional_rules` in `types/response.ts` + barrel (~5 min)
**Files:** mcp-server/src/types/response.ts, mcp-server/src/types/index.ts
**Action:** Make `data_freshness` nullable, add the `AdditionalRulesSection` type + section field, extend `Warning.section`.
**Details:**
- In `response.ts`: change `GetRegulationsResponse.meta.data_freshness` from its current object type to `<that same object type> | null`.
- Add a new exported interface `AdditionalRulesSection { rules: VerbatimRule[]; source: SourceCitation }`. `SourceCitation` is already imported from `./schema.js`; **`VerbatimRule` is NOT yet imported — add `VerbatimRule` to the existing `import type { … } from "./schema.js"` block in `response.ts`** (it currently pulls `SourceCitation`/`DrawSpec`/`ReservedPool`/`ClosurePredicate`/`WeaponType`/`Residency`/`GeometryRole`). Do NOT redefine `VerbatimRule`.
- Add `additional_rules: AdditionalRulesSection | null` to `GetRegulationsResponse` (place it alongside the other always-present null-bearing sections, matching `architecture.md` §"Response shape").
- Add `"additional_rules"` to the `Warning.section` string-union (it currently is `"seasons" | "tags" | "methods" | "reporting" | "contacts" | "overall"`).
- In `types/index.ts`: add `export type { AdditionalRulesSection } from "./response.js";` alongside the existing response-type re-exports (match the existing barrel style — `.js` extension, `export type`).
**Verify:** `cd mcp-server && npx tsc --noEmit` (expected to FAIL until T2 lands because the `output-schema.ts` `AssertEqual` guards reference these types and the schema hasn't caught up — that is acceptable for this task; the compile error must be ONLY the output-schema drift-guard mismatch, no error inside `response.ts`/`index.ts` themselves). Re-verify green after T2.
**UI:** no

### T2: Decision 1 + `additional_rules` schemas in `output-schema.ts` (~5 min)
**Files:** mcp-server/src/output-schema.ts
**Depends on:** T1
**Action:** Add `verbatimRuleSchema` (net-new) + `additionalRulesSectionSchema`, drop `sources.min(1)`, make `data_freshness` nullable, add `additional_rules` to the envelope, extend `warningSchema.section`.
**Details:**
- Add a NEW `verbatimRuleSchema = z.object({ text: z.string(), page_reference: z.string().nullable(), confidence: confidenceSchema, source: sourceCitationSchema })` — confirm the exact `VerbatimRule` field names/types by reading its definition in `types/schema.ts` and match them precisely (page_reference nullability, any additional fields). Reuse the existing `confidenceSchema` and `sourceCitationSchema` already defined in this file. Add the paired `AssertEqual` drift-guard (`const _assertVerbatimRule: AssertEqual<z.infer<typeof verbatimRuleSchema>, VerbatimRule> = true;`) mirroring the existing per-schema guards. **`VerbatimRule` is NOT currently imported into `output-schema.ts` — add it** (from `./types/schema.js`, matching the existing type-import style).
- Add `additionalRulesSectionSchema = z.object({ rules: z.array(verbatimRuleSchema), source: sourceCitationSchema }).strict()` + its paired `AssertEqual` guard against `AdditionalRulesSection`. **`AdditionalRulesSection` is NOT currently imported — add it to the existing `import type { … } from "./types/response.js"` block** (which currently pulls `Coverage`/`Warning`/`SeasonsSection`/`TagsSection`/`MethodsSection`/`ReportingSection`/`ContactsSection`/`GetRegulationsResponse`).
- In `getRegulationsResponseSchema`: drop `.min(1)` from the `sources` array (leave `z.array(sourceCitationSchema)`); change the `data_freshness` object to `.nullable()` (keep its `.strict()` — `z.object({...}).strict().nullable()`); add `additional_rules: additionalRulesSectionSchema.nullable()` to the envelope object.
- In `warningSchema`: add `"additional_rules"` to the `section` `z.enum([...])`.
- Keep every existing `AssertEqual`/`SameKeys` guard; the `_assertGetRegulationsResponse` guard must now compile against the T1-updated type.
**Verify:** `cd mcp-server && npx tsc --noEmit` — MUST be green now (T1 + T2 together restore the type↔schema equality).
**UI:** no

### T3: Generalize the builder + nullable `buildDataFreshness` + thin-text acknowledges `additional_rules` (~5 min)
**Files:** mcp-server/src/response-builder.ts
**Depends on:** T1, T2
**Action:** Make `buildDataFreshness` return `null` on empty; generalize `buildStructuredToolResult`; keep `gateBySchemaVersion` unchanged.
**Details:**
- `buildDataFreshness`: change the empty-`sources` branch from `throw` to `return null`; change the return type to `<existing freshness object type> | null`. The non-empty path is unchanged. (It stays a "compute freshness from ≥1 source, else null" function — no throw.)
- Generalize `buildStructuredToolResult` to:
  ```
  export function buildStructuredToolResult<T extends { meta: { warnings: Warning[] } }>(
    payload: T,
    schema: z.ZodType<T>,
    warnings: Warning[],
    renderText: (payload: T) => string,
  ): { structuredContent: Record<string, unknown>; content: { type: "text"; text: string }[] }
  ```
  (Use whatever the current exact return type is — do not change the return shape.) The body: assign the passed `warnings` into `payload.meta.warnings` (the builder is the SOLE writer of `meta.warnings`), then `schema.safeParse(payload)`, throw on failure exactly as today, produce `structuredContent` (the sanctioned `payload as unknown as Record<string, unknown>` cast stays) and `content[0].text = renderText(payload)`. Do NOT hard-call `renderThinText` anymore.
  - If a tighter generic bound than `{ meta: { warnings: Warning[] } }` is awkward, constrain minimally so the warnings-assignment typechecks; the narrower S09.2/S09.3 envelopes must still satisfy it. Avoid `any`.
- Keep `renderThinText` exported and unchanged EXCEPT: add a mechanical, field-derived line acknowledging the new section, e.g. `additional_rules: ${payload.additional_rules !== null ? "present" : "null"}` (presence flag only — NOT a paraphrase/overview, per ADR-013/ADR-008). It stays `GetRegulationsResponse`-typed and will be passed as the `renderText` arg for `get_regulations`.
- `gateBySchemaVersion` signature/behavior UNCHANGED (`{ included, warnings }`).
**Verify:** `cd mcp-server && npx tsc --noEmit` (expected to FAIL only at the not-yet-updated call sites in `health-check.ts` + `tests/response.test.ts` — those are T6/T8; no error inside `response-builder.ts` itself).
**UI:** no

### T4: Create the thin `get_regulations` handler (~5 min)
**Files:** mcp-server/src/tools/get-regulations.ts
**Depends on:** T1, T2, T3
**Action:** A thin handler that resolves ONE in-coverage point and composes a valid Shape C envelope.
**Details:**
- Export `getRegulationsInputSchema = z.object({ lat: z.number(), lng: z.number(), species: z.string(), date: z.string() })` and the handler `getRegulationsHandler(args, extra)`.
- Read column/table names from the migrations in `supabase/migrations/` and `types/schema.ts` (do NOT guess). Resolution: `extensions.ST_Covers(geom, extensions.ST_GeogFromText('SRID=4326;POINT(<lng> <lat>)'))` against `geometry` — **lng first** in the WKT; `ST_Covers(polygon_geom, point)` (geom is arg 1). Read `geometry.state` from the covering row (an OUTPUT). No `::geometry` cast / no WKT round-trip for the resolution predicate. All downstream queries carry the resolved `state`.
- Then `jurisdiction_binding` (join on `geometry_id`) → `regulation_record` (flat FK cols `regulation_record_state/_jurisdiction_code/_species_group/_license_year`) filtered by the resolved `state` and the input `species` (matched against `regulation_record.species_group`) → the season link (`regulation_season` on the 4-col composite → `season_definition`) to populate `seasons.windows`.
- Use `db.ts` ONLY: `const client = createDbClient(dsn); try { ... await client.query(...) } finally { try { await client.close(); } catch { /* swallow teardown */ } }`. Positional `$1…` params, fixed SQL strings. Read the DSN from the same runtime env var `db.ts`/`health-check.ts` already use — `SUPABASE_READONLY_DSN` (confirm by reading `db.ts`; do not invent). Note this is DISTINCT from `TEST_READONLY_DSN`, which only gates the live tests (T10), not the handler.
- Compose the `GetRegulationsResponse`: populate `resolved.jurisdiction` (non-null for an in-coverage point), `seasons.windows` (≥1), `sources` (≥1), `meta.coverage = { jurisdiction:"full", species:"full", overall:"full" }`, `meta.data_freshness = buildDataFreshness(sources, generatedAt)`, `meta.schema_version = 2`, `meta.generated_at`, `meta.warnings = []`. Sections not needed for the thin happy-path (`tags`/`methods`/`reporting`/`contacts`/`additional_rules`) may be `null` OR populated-but-empty as the schema allows — keep it minimal and schema-valid; do NOT build the full composite (that is S09.1b). Gate rows via `gateBySchemaVersion` and thread the collected `warnings` into the builder.
- Return `buildStructuredToolResult(response, getRegulationsResponseSchema, warnings, renderThinText)`.
- **This is the thin happy-path only.** Out-of-scope/edge-case handling, the ≤N-query bound proof, coverage tri-state boundaries, and byte-identity are S09.1b — do not implement them here. Schema-generic: no `if state === 'US-MT'` branches; no `any`.
**Verify:** `cd mcp-server && npx tsc --noEmit`
**UI:** no

### T5: Delete the bootstrap + register `get_regulations` in `server.ts` (~3 min)
**Files:** mcp-server/src/server.ts
**Depends on:** T4
**Action:** Remove `initializeEmptyToolRegistry` entirely; register the real tool.
**Details:**
- Delete the `initializeEmptyToolRegistry` function definition AND its call inside `createMcpServer()` (the register-then-remove `__bootstrap_noop__` idiom goes away completely). Remove any now-unused imports.
- Inside `createMcpServer()` register the tool: `server.registerTool("get_regulations", { description: <one-line>, inputSchema: getRegulationsInputSchema, outputSchema: getRegulationsResponseSchema, annotations: READ_ONLY_TOOL_ANNOTATIONS }, getRegulationsHandler)`. Import from `./tools/get-regulations.js`, `./output-schema.js`, `./response-builder.js` as appropriate (match the project's `.js`-extension ESM import style).
**Verify:** `cd mcp-server && npx tsc --noEmit`
**UI:** no

### T6: Reconcile the `health-check.ts` fixture + 4-arg builder call (~3 min)
**Files:** mcp-server/src/health-check.ts
**Depends on:** T3
**Action:** Make the smoke fixture satisfy the Decision-1 invariant and update the builder call.
**Details:**
- The fixture builds `coverage:{...:"none"}` but with non-empty `sources` + non-null `data_freshness`. Change it to `sources: []` and `data_freshness: null` (Option A — the clean total-coverage-gap shape). If `additional_rules` is now required on the envelope, set it to `null` (consistent with `coverage.overall:"none"`).
- Update the `buildStructuredToolResult(fixture)` call to the 4-arg form: `buildStructuredToolResult(fixture, getRegulationsResponseSchema, [], renderThinText)`.
- **Imports:** add `getRegulationsResponseSchema` via a new `import { getRegulationsResponseSchema } from "./output-schema.js";` (health-check.ts currently imports nothing from output-schema); add `renderThinText` to the existing `import { … } from "./response-builder.js";` line (T3 keeps `renderThinText` exported).
- **Dead-import cleanup:** after switching the fixture to `data_freshness: null`, the `buildDataFreshness(...)` call is gone — remove the now-unused `buildDataFreshness` import from `health-check.ts` (strict mode / `noUnusedLocals` will otherwise flag it).
- Do NOT change what `runHealthCheck` returns or its `envelope_valid`/`db_reachable` contract.
**Verify:** `cd mcp-server && npx tsc --noEmit && npx vitest run tests/health-check.test.ts`
**UI:** no

### T7: Exact-tool-set assertion in `server.test.ts` (~4 min)
**Files:** mcp-server/tests/server.test.ts
**Depends on:** T5
**Action:** Replace the two bootstrap tests with one exact-registered-tool-set assertion.
**Details:**
- Delete the `"tools/list returns an empty array — registry-empty lock"` test and the `"tools added later ... additive ... extension contract"` test.
- Add one test that calls the existing `setup()` helper, lists tools via the same mechanism those tests used, and asserts `tools.map(t => t.name)` deep-equals exactly `["get_regulations"]` (no `__bootstrap_noop__`, no health/internal tools). Keep the `afterEach` cleanup. This is the UAT #1 guard.
- Preserve all other tests in the file unchanged.
**Verify:** `cd mcp-server && npx vitest run tests/server.test.ts`
**UI:** no

### T8: Update `response.test.ts` — 4-arg call sites, flip empty-sources test, add gating + negative + freshness-null tests (~5 min)
**Files:** mcp-server/tests/response.test.ts
**Depends on:** T3
**Action:** Migrate call sites to the generalized builder and cover Decision-1/Decision-3 behavior.
**Details:**
- **First:** add `additional_rules: null` to the shared `makeResponse()` base object literal (the `GetRegulationsResponse` fixture factory used by nearly every test in this file) — after T1 adds the `additional_rules` field to the type, every `makeResponse()` call otherwise fails to typecheck. This is the highest-volume change in the file.
- Update every `buildStructuredToolResult(x)` call to the 4-arg form `buildStructuredToolResult(x, getRegulationsResponseSchema, <warnings|[]>, renderThinText)`.
- The existing test `"negative: throws when sources is empty (...)"` must FLIP: with Decision 1, a `coverage:"none"` payload with `sources: []` + `data_freshness: null` is now VALID and the builder must NOT throw. Rewrite it to assert the builder succeeds on that fixture (and its `structuredContent.meta.data_freshness === null`, `sources` empty).
- Add a test: `buildDataFreshness([], generatedAt)` returns `null` (Decision 1).
- Add the **schema-version gating** test (Decision 3(a)): construct a payload whose section carries a synthetic unsupported `schema_version` row; run it through the handler's gating path (or directly: call `gateBySchemaVersion([...])`, thread the returned `warnings` into `buildStructuredToolResult`); assert the unsupported row is EXCLUDED from `structuredContent` and `meta.warnings` contains an `UNSUPPORTED_SCHEMA_VERSION` entry with `section:"overall"`, written by the builder.
- Add the **negative** test (Decision 3(b)): a payload with a server-composed extra key (e.g. `overview`) OR a missing required section causes `buildStructuredToolResult` to THROW (generalization didn't weaken S08.3 `.strict()` validation).
- Keep all unrelated tests intact.
**Verify:** `cd mcp-server && npx vitest run tests/response.test.ts`
**UI:** no

### T9: Rec 5 single-read-path guard in `boundary.test.ts` (~4 min)
**Files:** mcp-server/tests/boundary.test.ts
**Depends on:** T4 (so the new tool file exists and is covered)
**Action:** Add a test that only `db.ts` opens a DB connection.
**Details:**
- Using the existing helpers (`collectTsFiles(srcDir)`, `parseSourceFile`, `callsToIdentifier`, `moduleSpecifiers`), add a test: for every `.ts` file in `src/` whose basename is NOT `db.ts`, assert `callsToIdentifier(sf, "postgres")` is empty AND no `moduleSpecifiers(sf)` entry resolves to the `postgres` package. Assert `db.ts` DOES call `postgres` (positive anchor so the guard can't silently pass if the pattern name changes).
- Mirror the structure/style of the existing Test 2 (no-`ingestion`-import) and Test 5 (`createDbClient` not at module scope).
**Verify:** `cd mcp-server && npx vitest run tests/boundary.test.ts`
**UI:** no

### T10: Thin happy-path live-DB test (~5 min)
**Files:** mcp-server/tests/get-regulations.test.ts
**Depends on:** T5
**Action:** A `TEST_READONLY_DSN`-gated test proving registration + envelope end-to-end.
**Details:**
- Mirror the gating pattern from `db.test.ts`/`health-check.test.ts`: `const DSN = process.env.TEST_READONLY_DSN;` a `it("requires TEST_READONLY_DSN when running in CI", ...)` guard, then `describe.skipIf(!DSN)(...)`.
- Inside: call `getRegulationsHandler` (or drive it through `createMcpServer`) with a known in-coverage MT point (a coordinate inside a known MT HD with a V1 species + in-season date — pick a defensible one and comment the source; the resolution + seasons must be present at `m1`). Assert: the result's `structuredContent` validates against `getRegulationsResponseSchema` (`.parse` doesn't throw), `resolved.jurisdiction` non-null, `meta.coverage.overall === "full"`, `sources.length >= 1`, `seasons.windows.length >= 1`.
- If a specific coordinate can't be confidently identified, the implementer may query `TEST_READONLY_DSN` once to pick a representative covered point + in-season date and hardcode it with a comment — but the test must NOT vacuously pass (assert non-empty results).
**Verify:** `cd mcp-server && npx vitest run tests/get-regulations.test.ts` (skips locally without DSN — acceptable; must not error)
**UI:** no

## Blast Radius
- **Do NOT modify:** `mcp-server/src/types/schema.ts` (3-place sync — `git diff` must be empty), `mcp-server/src/db.ts`, `mcp-server/src/router.ts`, `mcp-server/src/index.ts`, anything in `ingestion/` or `web/`, any `supabase/migrations/` file (read-only reference).
- **Watch for:** the `AssertEqual` drift-guards in `output-schema.ts` couple `types/response.ts` ↔ `output-schema.ts` — T1 and T2 must land together for `tsc` to go green. The `buildStructuredToolResult` signature change cascades to `health-check.ts` (T6) + `tests/response.test.ts` (T8) + the new handler (T4) + the new live test (T10) — `tsc` will flag any missed site. `warningSchema.section` (zod) and `Warning.section` (type) must both gain `"additional_rules"` in the same change (T1+T2).
- **Explicitly NOT in scope (S09.1b):** jurisdiction-resolution edge cases, the ≤N-`db.query` bound proof + max-16-overlay district, coverage tri-state boundary tests, `verbatim_rule`/`confidence`/`additional_rules` byte-identity vs a direct DSN read, the no-silent-authority-loss guard. Do not build these.

## Conventions
- ADR-011 (Shape C: always-present null-bearing sections; `data_freshness` null iff `sources` empty), ADR-013 (server returns structure; `content[0].text` mechanical, no overview/paraphrase), ADR-001/ADR-008 (verbatim, no paraphrase — the thin-text `additional_rules` line is a presence flag only), ADR-006 (schema-version gating), ADR-017 §2/§3 (confidence lives only on `regulation_record` + `VerbatimRule`; child rows have no confidence column).
- Follow the existing `AssertEqual`/`SameKeys` drift-guard convention for every new zod schema in `output-schema.ts`; every new envelope/section schema is `.strict()`.
- ESM `.js`-extension imports; no `any`; `tsc --noEmit` strict must stay green; the no-`ingestion`-import AST guard auto-covers new `src/` files.
- Connection lifecycle in handlers: `createDbClient` → use → `await client.close()` in a `finally` with teardown errors swallowed. `ctx.waitUntil` is NOT reachable from a tool callback.
- PostGIS: `extensions.`-prefixed; `POINT(lng lat)` (lng first); `ST_Covers(geom, point)`; resolution predicate needs no WKT round-trip; every spatial/state query carries the resolved `state`.
