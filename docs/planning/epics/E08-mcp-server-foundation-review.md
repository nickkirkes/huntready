# E08 — MCP Server Foundation — Pre-Implementation Epic Review

**Date:** 2026-06-26
**Reviewer:** Roughly `epic-reviewer` (opus), independent cross-story review
**Epic:** [`E08-mcp-server-foundation.md`](E08-mcp-server-foundation.md)
**Verdict:** **Ready** (with minor revisions recommended — no blockers)
**Resolution:** All six recommendations applied to the epic 2026-06-26 (PM). (1) S08.1 test-harness AC added; (2) S08.2 CI Postgres+PostGIS prerequisite AC added; (3) S08.4 Stage-1 "don't stand up the full OAuth provider" note added; (4) `reserved_pools` added to the `ResolvedTag` lock list; (5) S08.3 `response.ts` barrel-export-convention AC added; (6) ADR-024 flip noted as contingent on S08.2 Group B live-verification. cubic clean post-edits.

> This is an independent epic-level review dispatched via `/roughly:review-epic`, distinct from and on top of the E08 serving validation triad (MCP Protocol & Transport / Edge Runtime & Data-Access / Response-Envelope-Shape-C) whose findings are already applied in the epic's "Validation triad notes". It uses cross-story reasoning the per-dimension triad structurally couldn't: ordering, inter-story consistency, decomposition correctness, and whether E08 delivers everything E09/E10 need as a foundation.

---

## Summary

E08 is a well-constructed foundation epic. The 4-story decomposition (transport → DB → envelope → CORS/auth) is correctly ordered, the dependency chain is sound, and the serving triad's corrections are visibly baked into the ACs (per-request instantiation lock, role-level write-rejection, WKT round-trip idiom, Shape C exactness against `architecture.md`, the `Warning.code` flag-don't-decide). Load-bearing external claims grep-verified against the actual files: the Shape C types match `architecture.md` §"Response shape" exactly (incl. `ResolvedTag` carrying `quota`/`application_deadline`/embedded `DrawSpec` but not `quota_range`/`draw_spec_key`), the `is_stale` >180-day rule is correct, the scaffold facts (placeholder `index.ts`, `^1.9.0` SDK, `@supabase/supabase-js` PostgREST-client tension, `strict: true`) are accurate, and the ADR-status-flip / PM-doesn't-edit-ADR / flag-don't-decide discipline is followed throughout. The findings are cross-story gaps — chiefly **one undeclared prerequisite (the test harness) every AC silently depends on** — plus small consistency/positioning nits. None block.

---

## Findings by dimension

### Technical accuracy

- **[Low] (S08.1)** `tools` capability with an empty `tools/list` array — confirm SDK ergonomics at Stage-1. With `McpServer`/`createMcpHandler`, the `tools` capability is typically auto-declared as a side effect of *registering* a tool; declaring it with zero registered tools may need manual capability config. Deferral to Stage-1 is correct — flag this specific interaction so the implementer doesn't assume `registerTool()`-driven auto-capability.
- **[Info] (S08.4)** `@cloudflare/workers-oauth-provider` is a full OAuth provider, not a thin "seam toggle". The library wraps the entire Worker as an OAuth-protected provider; wiring it as a no-op toggle is non-trivial. Stage-1 should confirm the test-mode credential check does **not** require standing up the full provider (else S08.4 over-pulls library surface for a foundation).

### Best practices

- **[Medium] (S08.1 — single most actionable gap)** **No test runner / harness is declared, yet ~15 ACs require tests.** `mcp-server/package.json` has only `dev`/`build`/`start`/`lint` (`lint` = `tsc --noEmit`) — no `vitest`/`jest`/`node:test`, no `test` script. Every "a test asserts…" AC across S08.1–S08.4 assumes a CI test capability that doesn't exist. **Add an explicit S08.1 AC** to stand up the test harness + `test`/`test:ci` scripts + a CI invocation — the serving analog of the Python `pytest` baseline the project tracks (there's no "1907 + 4 skipped" equivalent being established yet).
- **[Low] (S08.3)** `src/types/index.ts` barrel re-export not addressed. S08.3 adds `response.ts` but no AC says whether the new response types are re-exported through the existing barrel. E09/E10 will import them — decide the convention now (barrel vs. direct import) so it isn't a per-tool coin-flip.

### Risks

- **[Medium] (S08.2)** **CI/local Postgres+PostGIS for the role-level write-rejection test is an unstated infra prerequisite.** The AC correctly demands SQLSTATE `42501` against a real SELECT-only role with the committed GRANT (and forbids a mock) — but that requires a Postgres-with-PostGIS service in CI (the smoke query is `extensions.`-prefixed). No AC provisions it; if CI has no Postgres, this Group A AC can't close at-merge and silently degrades to Group B. Add an AC/Context note that S08.2 stands up the CI Postgres+PostGIS service (or documents the local-only run path).
- **[Low] (S08.2 → E09)** The Hyperdrive-vs-serverless-HTTP choice forks secrets, dev-binding, and lifecycle; whichever path is chosen, E09/E10 inherit a hard "one connection acquisition per tool call, no cross-request pool" constraint. Carry it forward as an explicit E09 forward-note (reinforcement — the PRD E09 exit criteria already mention bounded round-trips).

### Overengineering

- **[Low] (S08.3)** The reusable-helper scope (server-side `outputSchema` validation + negative test + schema-version-gating helper + thin `content[0].text`) is at the high end for a tool-less epic, but justified (E09/E10 inherit; R4/R5 are real). Watch for gold-plating during implementation — one helper + one fixture is enough; don't build a generic schema-registry. Right-sized as written.
- **[Info] (S08.4)** Auth seam correctly right-sized (wired-but-unenforced, test-mode-only proof, deployed config open). No change.

### Acceptance-criteria quality

- **S08.1** — Strong (per-request-instantiation lock, SDK-negotiated `protocolVersion` assertion, `tools/list` length===0 + registry-empty lock). Nit: ensure the `mcp-remote` "documented note" lands somewhere durable (working note/README stub), not just the PR description.
- **S08.2** — Most rigorous in the epic; the mock-doesn't-satisfy clause is excellent. See the CI-Postgres prerequisite (Risks).
- **S08.3** — Exhaustive fixture-round-trip AC; `Warning.code` tension correctly flagged-not-decided with a concrete interim assertion. **[Low] Gap:** the `ResolvedTag` explicit lock list omits `reserved_pools: ReservedPool[]` (present in `architecture.md`). The "match exactly" umbrella covers it, but since the AC enumerates `draw_spec`/`application_deadline`/omitted fields, add `reserved_pools` for symmetry.
- **S08.4** — Solid; the `401` + spec-shaped `WWW-Authenticate`/resource-metadata assertion (not a bare token compare) is testable; the boundary-import guard mirrors the ingestion `TestNoStateAdapterImports` correctly.

### Dependencies

- **Ordering is correct:** transport (S08.1) → DB (S08.2) → envelope (S08.3) → CORS/auth (S08.4). S08.3's "internal health check exercises a real DB read (S08.2)" explicitly depends on S08.2 (verified), and on S08.1's tool-count lock (verified). S08.4 is genuinely independent; placing it last is fine.
- **R0 roadmap reconciliation** correctly positioned as a blocker on *implementation*, not planning. Correct.
- **The `Warning.code` schema-version gap** correctly a non-blocker (flag-don't-decide + interim test assertion). The 6-value union genuinely has no schema-version member — the flag is real, not invented.
- **[Low] ADR-024 flip timing vs. Group B.** Known-issues says ADR-024 → `Accepted` "at S08.2 (driver chosen + access layer ships)", but the *live* read-only-enforced edge read is Group B operator-pending. Flag the flip as **contingent on S08.2 Group B live-verification**, not auto-flipping at Group A merge — otherwise the ADR reads Accepted before its enforcement claim is live-verified.

---

## Recommendations (prioritized)

1. **(S08.1, Medium)** Add a **test-harness AC** — stand up the serving test runner + `test`/`test:ci` scripts + CI invocation in S08.1 (the `pytest`-baseline analog every downstream "a test asserts…" AC depends on).
2. **(S08.2, Medium)** Provision **CI Postgres+PostGIS** as an explicit prerequisite for the role-level write-rejection + `ST_*` smoke ACs, or the strongest Group A safety AC silently slips to Group B.
3. **(S08.4, Low)** Confirm at Stage-1 the test-mode auth seam does **not** require standing up the full `@cloudflare/workers-oauth-provider`.
4. **(S08.3, Low)** Add `reserved_pools` to the `ResolvedTag` explicit lock list.
5. **(S08.3, Low)** Decide the `response.ts` barrel-export convention in `src/types/index.ts`.
6. **(Known issues, Low)** Note ADR-024's flip is **contingent on S08.2 Group B** live-verification, not the Group A merge.

**No structural blockers.** The decomposition is right (4 stories, none should split or merge; the only "missing story" — error capture — is correctly E11 per the PRD, not under-scoped here). E08 delivers what E09/E10 need: transport, a single read path with inherited WKT idiom + lifecycle constraint, a proven Shape C envelope, and the reusable gating/annotation mechanisms.
