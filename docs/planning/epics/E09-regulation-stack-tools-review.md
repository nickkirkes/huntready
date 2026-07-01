# E09 — Regulation-stack Tools — Pre-Implementation Epic Review

**Date:** 2026-06-30
**Reviewer:** Roughly `epic-reviewer` (opus), independent cross-story review
**Epic:** [`E09-regulation-stack-tools.md`](E09-regulation-stack-tools.md)
**Verdict:** **Needs Revision** → **all actionable findings addressed 2026-06-30** (see Resolution)

> Independent epic-level review on top of the E09 serving triad (Source-Faithfulness/Citation · Shape-C Fidelity · Query-Correctness/Coverage-Signal, findings already applied) — using cross-story reasoning the per-dimension triad couldn't. Most load-bearing claims verified accurate against the live files; the issues below are a cross-story technical-feasibility error, an internal-consistency snag, and an overload/split.

## Resolution (2026-06-30, PM — all actionable findings applied to the epic)

1. **(Blocker) `ctx.waitUntil` teardown** — replaced across S09.1/S09.2/S09.3 + the commitments table with **`await client.close()` in a `finally` (errors swallowed)**, matching `health-check.ts` (the reachable pattern; `ctx` is not threaded into tool callbacks). The earlier S08.2/S08.3 forward-note that said "`ctx.waitUntil`, never await inline" was aspirational/incorrect and is corrected here.
2. **(Blocker-adjacent) health-check fixture** — added an S09.1 AC to reconcile `mcp-server/src/health-check.ts`'s `coverage:none` fixture (currently non-empty `sources` + non-null `data_freshness`) with S09.1's new invariant (update to `sources:[]`/`data_freshness:null`, or explicitly carve it out as a deliberately-non-conforming smoke fixture) + re-run `health-check.test.ts`.
3. **(Should-fix) S09.1 split** — made it a **planned split at a named seam**: **S09.1a (foundation)** vs **S09.1b (full composite)**; every S09.1 AC is tagged `[1a]`/`[1b]`; S09.2/S09.3 depend only on S09.1a.
4. **(Should-fix) Decision-3 builder sink** — specified: **`gateBySchemaVersion` stays pure** (`{included, warnings}`, `health-check.ts` unaffected); **`buildStructuredToolResult` is the sole writer of `meta.warnings`** and requires the accumulated warnings as an argument the handler threads through (the per-tool gating test is the backstop).
5. **(Should-fix) "Bounded" made objectively testable** — assert the handler issues **≤N `db.query` calls independent of overlay/binding count** on the max-16-overlay district.
6. **(Should-fix) Live-data hedge** — applied S09.3's "assert-on-available-row-or-document-gap" hedge to S09.1's A/B-asymmetry (cite **HD 170**, true at `m1`) + region-reporting + populated-empty happy-path ACs.
7. **(Minor)** `registerTool` config shape + double-validation note (SDK output validation + `buildStructuredToolResult.safeParse`); Decision-2 replaces **both** `server.test.ts` locks (empty-registry + additive); `geometry.kind`/`role` enum-drift caution (cite migration-current sets if enumerated).

cubic clean post-edits.

## Verdict & summary

E09 is well-grounded and disciplined — the serving triad did real work and most load-bearing claims verify accurate (4-FK-col composite link joins, `draw_spec_key` jsonb soft FK, `geometry.geom` geography + GiST, `ST_Covers` arg order + lng-first WKT, granular `species_group` corpus, the `additional_rules` + `data_freshness` architecture.md/ADR-011 amendments, `.strict()` envelopes). The decomposition (flagship-establishes / two-reuse) and dependency ordering are sound. **Needs Revision** rested on: one cross-story feasibility error recurring in every story (`ctx.waitUntil`), one internal-consistency snag (the E08 health-check fixture vs S09.1's new invariant), and S09.1 being overloaded.

## Findings by dimension

### Technical accuracy
- **🔴 BLOCKER — `close()` via `ctx.waitUntil(...)` is unreachable from a tool handler.** A tool registered with `server.registerTool` runs as a `ToolCallback(args, extra)`; `RequestHandlerExtra` has `signal`/`sessionId`/`requestInfo`/`auth` — no Worker `ExecutionContext`/`waitUntil`. `ctx` exists only in `index.ts`'s `fetch(request, env, ctx)`. Zero `waitUntil` usages exist in `mcp-server/`; E08's `health-check.ts` `await`s `close()` inline in `try/finally`. → **Resolution #1.**
- **🟡 SHOULD-FIX — `registerTool` config + double-validation.** SDK 1.29.0 config is `{ title?, description?, inputSchema?, outputSchema?, annotations?, _meta? }`; `outputSchema` takes a zod raw shape or schema (`.strict()` ZodObject is fine). The MCP SDK also validates output against `outputSchema`, so there are two passes (SDK + `buildStructuredToolResult.safeParse`) — note it. → **Resolution #7.**
- **🟢 Verified accurate** (triad did well): link-table 4-col composite join predicate; `draw_spec_key` jsonb; `geometry.geom` geography + GiST; `regulation_record.additional_rules` jsonb; `VerbatimRule` type; `DbClient.query<T>`; `gateBySchemaVersion`/`buildDataFreshness`/`getRegulationsResponseSchema` current shapes; the architecture.md amendments all landed.

### Best practices
- **🟡 SHOULD-FIX — enum drift awareness.** `jurisdiction_binding.role` (8 values incl. `no_hunt_zone`, added `20260603000000`) and `geometry.kind` (`'state'` added `20260504032424`) — both consistent in `schema.ts`/zod, but if any AC enumerates them, cite the migration-current set (the project's documented line-drift mode). Resolution reads `geometry.state`, not `kind`, so not load-bearing. → **Resolution #7.**
- **🟢 Good:** no-MT-branch/schema-generic, single-read-path guard, `extensions.`+WKT idiom correctly scoped (NOT the `ST_GeogFromText` predicate), `.strict()` + drift-guards, flag-don't-decide on catalog scope.

### Risks
- **🔴 BLOCKER-adjacent — internal consistency:** `health-check.ts` builds a `coverage:none` response with non-empty `sources` + non-null `data_freshness` — a canonical example of the exact state S09.1's new invariant forbids. The epic didn't mention `health-check.ts`. → **Resolution #2.**
- **🟡 Decision-3 "builder-owned sink" under-specified** for a function (`gateBySchemaVersion`) that today returns a value and is called by `health-check.ts` + tests. → **Resolution #4.**
- **🟡 Coverage populated-empty↔"full"** needs a concrete MT example (is there a resolved record with zero reporting obligations?) — apply the assert-or-document hedge. → **Resolution #6.**

### Overengineering
- **🟡 S09.1 is overloaded** (jurisdiction resolution + bounded composite + builder generalization + 4 decisions + `additional_rules` end-to-end + 13 ACs). Split at a named seam: S09.1a foundation / S09.1b composite; S09.2/S09.3 depend only on the foundation half. → **Resolution #3.**
- **🟢 Not overengineered:** the `additional_rules` section (reuses `VerbatimRule`, one wrapper), the catalog scope (option a, deferred to Stage-1), the narrower-envelope reuse.

### Acceptance-criteria quality
- **🟡 "Bounded (target: one query)" not objectively testable** — state the measurable assertion (≤N `db.query` calls independent of binding/overlay count). → **Resolution #5.**
- **🟡 Several "Group A at-merge" ACs need live MT rows** that may not exist — apply S09.3's assert-or-document hedge (cite HD 170 for A/B). → **Resolution #6.**
- **🟢 Strong ACs:** lat/lng-transposition guard, byte-identity-vs-direct-DSN, the `--- COMMENTS ---` case, confidence-inherited assertion, the negative validation test, the no-silent-authority-loss guard, the `MT-STATEWIDE-antelope` 2-NOTE anchor.

### Dependencies
- **🟢 Ordering correct** (S09.1 establishes → S09.2/S09.3 reuse; the narrower tools correctly don't depend on jurisdiction resolution). E08 dependency, the E09→E10 audit gate, and CO-N/A-until-`m2` markers all correctly stated. E10-reuse note accurate.
- **🟡 Minor — Decision-2** replaces **both** `server.test.ts` locks (empty-registry + additive-extension); name both. → **Resolution #7.**

**No structural blockers remain after the resolution edits.** The decomposition is right (with S09.1 now split at the named seam); E09 delivers the generalized builder + `ST_Covers` resolution pattern E10 needs.
