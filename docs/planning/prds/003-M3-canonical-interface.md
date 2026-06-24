# PRD 003 — M3: Canonical Interface Live (MCP Server)

**Number:** 003
**Scope:** Milestone M3 (entire milestone; one carry-forward epic + four serving epics)
**Status:** Active
**Date:** 2026-06-24
**Author:** Nick Kirkes
**Thinking-layer references:** [`roadmap.md`](../../roadmap.md), [`context.md`](../../context.md), [`architecture.md`](../../architecture.md), [`open-questions.md`](../../open-questions.md)
**Load-bearing ADRs:** [ADR-001](../../adrs/ADR-001-authority-preserved.md), [ADR-002](../../adrs/ADR-002-mcp-canonical-interface.md), [ADR-003](../../adrs/ADR-003-ingestion-upstream-offline.md), [ADR-004](../../adrs/ADR-004-supabase-postgres-postgis.md), [ADR-005](../../adrs/ADR-005-python-for-ingestion-typescript-for-serving.md), [ADR-006](../../adrs/ADR-006-schema-versioned-from-day-one.md), [ADR-008](../../adrs/ADR-008-verbatim-regulation-text.md), [ADR-010](../../adrs/ADR-010-decomposed-entity-model.md), [ADR-011](../../adrs/ADR-011-shape-c-response-envelope.md), [ADR-012](../../adrs/ADR-012-draw-mechanics-sibling-entity.md), [ADR-013](../../adrs/ADR-013-server-returns-structure-client-composes-presentation.md), [ADR-014](../../adrs/ADR-014-source-citation-gis-layer-document-type.md), [ADR-017](../../adrs/ADR-017-confidence-calibration.md)
**New ADRs introduced alongside this PRD:** [ADR-023](../../adrs/ADR-023-remote-mcp-server-posture.md) (remote MCP posture — Cloudflare Workers + Streamable HTTP + the V1 static-bearer-token auth seam; resolves Q5/Q6) and [ADR-024](../../adrs/ADR-024-edge-runtime-postgres-access.md) (edge-runtime Postgres access, refining ADR-003). Both are `Proposed` pre-implementation and flip to `Accepted` as the implementing epics (E08/E11) ship.

---

## Context

M2 is closing as this PRD is authored: Colorado ingestion is complete through the geometry layer (E05) and most of the regulation-text layer (E06), with the final E06 stories (S06.8–S06.11) in flight. M3 does not wait for the `m2` tag. Per the roadmap dependency graph, M1 unblocks both M2 and M3, and the two run in parallel — M3 builds the serving stack against the **Montana corpus**, which is frozen and complete at `m1`, and Colorado support "follows automatically once M2 lands" because the MCP server cannot distinguish the two states at the schema layer (the correctness property of the multi-state claim). This PRD is being drafted to parallelize M3 planning while M2 finishes.

M0–M2 built the data backend: a six-entity decomposed model (ADR-010) populated with two states' worth of real, source-cited, verbatim regulation data behind deny-all RLS. Nothing reads that data yet except direct service-role Postgres queries during UAT. M3 is where the data becomes *usable* — where the MCP server, the canonical interface per ADR-002, exposes the five V1 tools so an agentic client can hold a grounded conversation about hunting.

This PRD exists because M3 is the first milestone to leave the Python ingestion world and enter the TypeScript serving world (ADR-005's language boundary), and because a deliberate architectural decision taken at M3 planning time **diverges from the roadmap's original framing** of M3 as a local stdio server with an HTTP shim. The roadmap is being evolved to match; the divergence, its rationale, and its consequences are surfaced here before epic planning begins, per the roadmap's own rule that PRD/roadmap disagreements are surfaced to the human rather than silently resolved.

### The posture decision (roadmap divergence)

The roadmap (M3 § "Canonical interface live") frames the MCP server as *installable locally*, registering with Claude Desktop over stdio, with a REST HTTP shim for the web companion. During M3 planning (2026-06-24) the decision was taken — with explicit human sign-off — to build M3 as a **remote, authenticated-capable MCP server on the current spec transport** instead:

- **Transport:** Streamable HTTP (the current MCP spec transport), built against the **2025-11-25 stable** spec using Cloudflare's stateless `createMcpHandler`/`WorkerTransport`, designed forward-compatible with the 2026-07-28 release candidate (no reliance on `Mcp-Session-Id` semantics) — not stdio-as-primary. A stdio entrypoint is retained for local development via the `mcp-remote` proxy, which preserves the roadmap's "registers with Claude Desktop" signal. (`mcp-remote` is a transitional bridge for stdio-only clients; it may be retired as clients gain native remote-MCP support, so the local-Claude-Desktop path is a convenience, not a permanent contract.)
- **Deployment target:** Cloudflare Workers, using the Agents-SDK remote-MCP toolchain. HuntReady's tools are stateless reads, so the stateless `createMcpHandler` path is used — `McpAgent`/Durable Objects (per-session state) are not needed for V1, which also sidesteps Durable-Object hibernation concerns. This resolves Q6, noting Cloudflare Workers was *not* among Q6's original option set (Railway/Fly/Render/Vercel); it is selected because the remote-MCP posture changed the decision frame (R2).
- **Auth:** minimal but OAuth-2.1-*ready* for V1. Because the data is public (no resource owner), the V1 gate's job is access **metering / abuse-control**, not authorization — so V1 ships a **static bearer-token / API-key checkpoint** as Worker middleware (validate an `Authorization: Bearer <token>` against a secret in Workers Secrets), *not* a full OAuth flow. `@cloudflare/workers-oauth-provider` (OAuth 2.1 authorization-code + PKCE + RFC 7591 dynamic client registration) is the documented drop-in upgrade path for when a go-to-market strategy gives the auth model a subject to protect — it is *not* a V1 dependency. The spec makes authorization optional and directs stdio transports *not* to use it; a remote HTTP transport is what makes the authenticated-MCP spec exercisable at all.

The driver is production intent. M3's output is not only a portfolio artifact: the user intends to move HuntReady toward a production public service if it does not become an OnX engagement. A production public API wants edge autoscale, managed OAuth it does not have to secure itself, native WAF/rate-limiting in front of a public surface, and idle-cost-near-zero hibernation — all of which the Cloudflare remote-MCP path provides, and which become liabilities (a self-maintained OAuth server) or absences on a hand-rolled Node host. Shipping production-grade is also the stronger portfolio signal. The one real cost — Postgres is reached from the Workers edge runtime, not a long-running Node process — is an ADR-003 amendment, and under production framing it is an upgrade (Hyperdrive edge connection-pooling, and optional short-TTL caching bounded by the regulatory-freshness constraint in R1, for a read-heavy public-regulations API), not a compromise.

This is the **posture** sign-off (2026-06-24). The roadmap's M3 section itself has not yet been edited — it still describes the local-stdio + REST-shim framing. That reconciliation is a separate, explicit sign-off that lands before E08 begins (R0).

## Outcome

When M3 is complete, the observable state of the world is:

- A remote MCP server, deployed and reachable over HTTPS, exposes the five V1 tools (`get_regulations`, `check_land_status`, `list_seasons`, `get_tag_requirements`, `get_agency_contacts`) over the Streamable HTTP transport, backed by the Montana corpus (and Colorado automatically, once `m2` lands).
- Every tool returns a properly structured, source-cited response. `get_regulations` returns the Shape C envelope (ADR-011) with always-present, null-bearing sections; every response carries a `sources` array (ADR-001).
- An out-of-scope query (unsupported species, state, or coordinate outside coverage) returns a structured "not covered" response with explicit `coverage: "none"` signals — never a silent empty result.
- The server is installable by any MCP-capable client: remotely over Streamable HTTP, and locally for development via the `mcp-remote` proxy, registering cleanly with Claude Desktop.
- An OAuth-2.1-ready auth seam exists and gates access at the chosen V1 depth (a static bearer-token / API-key checkpoint for metering/abuse-control), with the integration point structured for a later full-OAuth upgrade.
- External error capture is integrated through a single integration point (Sentry or the Cloudflare-native equivalent); server errors are routed to an external service, not buried in application logs.
- The serving stack honors the architecture boundary: `mcp-server/` reads from Postgres and never imports from `ingestion/` (ADR-003, ADR-005). Postgres is reached from the edge runtime via Hyperdrive or the Supabase serverless driver per the ADR-003 amendment.
- The Montana ingestion data is unaffected — M3 writes no regulation data and runs no ingestion. Geometry pin-enforcement (E07) is the only ingestion-adjacent work, and it changes fetch-time validation, not loaded rows.
- The `m3` tag is pushed at the commit where M3 UAT passes.

The milestone exit criterion from the roadmap stands, evolved for the remote posture: an agentic client can hold a useful, grounded conversation with HuntReady about hunting in Montana, against a deployed remote server, with sources on every answer. Colorado support follows once M2 lands **without server code changes — given the schema-generic tool discipline (R7), and validated by the CO spot-checks in UAT #5/#6** (not assumed; checked).

## In scope

**Surface:** The MCP server (`mcp-server/`) and its five V1 tools. This is the canonical interface (ADR-002); M3 builds it and nothing else consumes it yet.

**Transport:** Streamable HTTP as the primary, deployed transport. A stdio/`mcp-remote` path for local development. No legacy HTTP+SSE transport (removed from the current spec).

**Tools (all five V1 tools per `architecture.md` § "The MCP server"):**

- `get_regulations(lat, lng, species, date)` — the headline composite tool. Returns the full `GetRegulationsResponse` Shape C envelope: resolved jurisdiction, seasons, tags (plural, A/B-aware), methods, reporting (plural, region-aware), contacts, `sources[]`, and `meta` with coverage/freshness/warnings.
- `check_land_status(lat, lng)` — access status for a point, via PostGIS point-in-polygon against the loaded `geometry` + `jurisdiction_binding` overlays (restricted areas, no-hunt zones). **V1 contract note:** this resolves against the PAD-US-derived restricted/no-hunt-zone overlays loaded in E05, and must correctly distinguish a true closure (`no_hunt_zone`) from a regulated-but-huntable `other_overlay` (e.g., the Air Force Academy per the S06.5/S06.10 disposition) — it does not collapse "restricted access" into "closed." `architecture.md`'s fuller "PAD-US + BLM PLAD, public/private status, land-management authority" framing is the eventual contract and is flagged for an `architecture.md` addendum; the V1 tool narrows to the loaded-overlay reality.
- `list_seasons(state, species, year)` — season windows for a state/species/year.
- `get_tag_requirements(state, species, year, residency)` — tag type(s), draw vs. general status, application deadlines, embedded `draw_spec` context, and purchase-flow links.
- `get_agency_contacts(lat, lng)` — regional warden, rules hotline, regional office for the district containing the point. **Data-source note:** agency contacts are *not* part of the M1/M2 regulation corpus — per Q9 they are a hand-curated CSV per state. Sourcing and loading that CSV (Montana, plus Colorado) is therefore **net-new M3 work** carved into E10, not "what M1+M2 loaded." (Open item: confirm whether any contacts CSV already exists from M0/M1 before E10 sources it fresh.)

**Response discipline:** Shape C (ADR-011) for `get_regulations`; structured `coverage` signals distinguishing "not applicable" (`null` section) from "not in dataset" (`coverage: "none"`); `sources[]` on every tool response (ADR-001); server returns structure, no server-composed `overview`/`headline` (ADR-013); confidence surfaced consistently across MT and CO (ADR-017's FINALIZE verdict); verbatim rule text passed through unaltered (ADR-008). Each tool declares an `outputSchema` and returns `structuredContent` as the source of truth, with `content[0].text` a thin derivative markdown rendering; each tool sets the read-only MCP annotations (`readOnlyHint: true`, `idempotentHint: true`, `openWorldHint: false`). **Schema-version gating per ADR-006:** a row with an unsupported `schema_version` is *excluded and surfaced in `meta.warnings`* — never silently dropped (that would violate the "never silent empty" principle) and never a hard error.

**Auth:** A minimal V1 gate — a **static bearer-token / API-key checkpoint** in Worker middleware, whose purpose on public data is access metering / abuse-control. Architected behind a single auth seam so the full OAuth 2.1 flow (authorization-code + PKCE + DCR via `@cloudflare/workers-oauth-provider`) drops in later without rebuilding. The full, GTM-determined model is out of M3 scope.

**CORS:** Because Q5 resolves to no-BFF (the M4 web app will call the Worker directly from the browser), the Worker emits CORS headers and handles `OPTIONS` preflight. The *mechanism* is M3; the allowed-origin *policy* is configurable and can be tightened in M4 (a permissive policy is acceptable for the public-data M3 demo window).

**Secrets:** The read DSN / token secret live in Workers Secrets (`wrangler secret put`), never in committed files — extending the M1 secrets-hygiene discipline to the serving stack.

**Deployment:** A deployed remote server on Cloudflare Workers, reachable over HTTPS, with a committed example client-config snippet at repo root (for `.mcp.json` / `claude_desktop_config.json`, invoking `mcp-remote`) and local-dev instructions. Deployment is in M3 scope precisely because the server is *remote* — there is no longer a "local only in M3, deploy in M4" split for the MCP server itself. (The web companion's deployment remains M4.)

**Edge-runtime Postgres access:** Read access from the Workers runtime per the ADR-003 amendment. The concrete driver — Cloudflare Hyperdrive (edge pooling, optional caching) vs. the Supabase serverless/HTTP driver — is selected by an E08 spike. Access is **read-only by enforcement, not just convention**: a dedicated SELECT-only Postgres role (preferred) or a read-only-transaction-pinned connection — *not* the write-capable service-role key — so a serving-path defect cannot mutate data. If Hyperdrive caching is enabled, it is short-TTL and a cache purge is part of the re-ingestion/deploy runbook (regulatory freshness is a correctness property per ADR-001 / `meta.freshness`); default-on caching is not assumed.

**Error capture:** A single external error-capture integration point (Sentry or Cloudflare-native equivalent) covering the server and its transport.

**Tests:** Per tool, at minimum one happy path and one missing-data path. Plus transport conformance and response-shape conformance coverage.

**M2 carry-forward + ingestion hardening (E07):** PAD-US geometry pin-enforcement (Q21 option (a) — the two-gates fetch model mirroring the PDF loaders' `expected_sha256`), plus the post-E06 ingestion-hygiene items agreed at E07 planning (Known Issue #7 overlay-builder shared-lib extraction; MT extractor migration to `write_extraction_artifact`). This is the only ingestion-side work in M3.

**Phasing:** Five epics (E07–E11) as described below.

## Out of scope

Explicitly named to prevent scope creep:

- **The web companion and its deployment.** M4. M3 ships the MCP server and its transport; the web app stays at its M0 placeholder. Q5 is resolved here (no BFF — see "Open decisions resolved during M3"), but no `web/` implementation happens in M3.
- **The Claude Code plugin.** M5.
- **The full, GTM-determined production auth model.** M3 ships the auth *seam* at minimal depth. The IdP choice, scope design, API-key tiering, B2B access, and any monetization/metering are explicitly deferred to a post-V1 decision driven by go-to-market strategy (new open question — see below). M3 does not lock them.
- **New ingestion or new state data.** M3 reads the regulation/geometry corpus exactly as M1+M2 loaded it. No new regulation rows; no new state. The one carve-out is the hand-curated agency-contacts CSV (Q9), which the regulation pipeline never produced and which `get_agency_contacts` requires — sourcing/loading it is in-scope M3 work (E10), not regulation ingestion. E07's pin-enforcement changes fetch-time validation only.
- **Re-ingestion of Montana or Colorado.** Frozen at `m1` / `m2`. E07 touches ingestion fetch-validation code and the named hygiene items, not loaded rows.
- **Server-side composition of `overview`/`headline` text.** ADR-013. The server returns structure; clients compose. (A thin `content[0].text` markdown derivative for non-`structuredContent` clients is permitted per `architecture.md` § response shape, but it is a derivative, not a source of truth.)
- **Schema changes to the six-entity model.** M3 is a read surface. If a tool genuinely cannot express something the schema holds, that is a flag-and-discuss event, not a silent schema edit. The ADR-003 amendment and the new deployment/auth ADRs concern serving infrastructure, not the data model.
- **RLS policy changes.** The deny-all RLS posture stands unchanged; M3 adds no user-scoped RLS policies. (Provisioning a dedicated SELECT-only Postgres role for the serving connection — a `GRANT`, not an RLS policy — is in scope per the read-only-enforcement decision above; it does not alter any RLS policy.)
- **Caching strategy tuning, query-performance tuning, rate-limit policy design.** Hyperdrive caching and Cloudflare edge rate-limiting are available and used at sane defaults; tuning them is V2. (Rate-limit *policy* is GTM-adjacent and deferred with the auth model.)
- **`mcp-server/` importing from `ingestion/`.** Hard architectural boundary (ADR-003, ADR-005). The serving stack requires no Python.

## Phasing and rationale

M3 decomposes into five sequential epics. The "Why sequential" rationale follows.

### E07 — M2 carry-forward and serving-stack preparation

**Outcome:** PAD-US geometry pin-enforcement is implemented (Q21 option (a)): the geometry fetch path takes an `expected_sha256`/`expected_layer_hash` and refuses to write when the live re-fetch diverges from the committed manifest, mirroring the PDF loaders' two-gates model and the `*-pending-reextraction.flag` recovery workflow. The agreed post-E06 ingestion-hygiene items land (Known Issue #7 overlay-builder shared-lib extraction; MT extractor migration to `write_extraction_artifact`). Any serving-stack scaffolding prerequisites identified during E07 planning (e.g., the edge-runtime-Postgres *principle* captured in ADR-024, with the concrete driver deferred to E08's spike) are recorded.

**Why first:** Production intent makes the dev/prod PAD-US drift surface real, not theoretical — Q21's own trigger language says "if dev/prod parity matters → ship (a)." Closing it before a prod environment ingests against live upstream sources matches the discipline that opened M2's E04 (close inherited hygiene debt before new work). It is also the cleanest place to fold the remaining ingestion-side carry-forward, since M3's other four epics touch no Python.

**Why isolated:** E07 is Python ingestion work; E08–E11 are TypeScript serving work. Bundling them would mix two toolchains and two reviewer skill-sets in one epic. Keeping E07 separate keeps the serving epics clean.

**Exit criteria for E07:** Geometry loaders enforce the committed manifest at fetch time with a documented drift-marker recovery path; new unit tests cover the gate and recovery; the agreed hygiene items merge with quality gates green and no regression to the M2 test baseline; the **ADR-003 amendment establishing the principle** (the serving stack reads Postgres from the edge runtime, not a long-running Node process) is drafted and accepted in principle (ADR-024 records it; it flips to `Accepted` at E08 when the access layer ships). The *concrete driver* (Hyperdrive vs. Supabase serverless driver) is deliberately deferred to E08's spike and recorded there as an addendum — E07 settles the principle, not the driver. No loaded rows change.

### E08 — MCP server foundation

**Outcome:** The MCP server bootstraps on the Streamable HTTP transport (Cloudflare Workers, stateless `createMcpHandler`); an E08 spike selects the edge Postgres driver (Hyperdrive vs. Supabase serverless driver) and records it as an ADR-003-amendment addendum; a read-only-enforced Postgres access layer (dedicated SELECT-only role or read-only-transaction pin) reaches Supabase from the edge runtime; CORS/preflight handling and the static-bearer-token auth-seam checkpoint are stood up; the Shape C response builder/envelope and the shared TypeScript types (`mcp-server/src/types/`) are wired and exercised end-to-end by one internal health check. The transport, the DB layer, and the envelope are the prerequisites every tool depends on.

**Why second:** Every tool reads through the same DB access layer and (for `get_regulations`) the same response builder. Standing up the transport + DB + envelope before any real tool means E09/E10 do not each re-solve connection, auth-seam, and serialization concerns. The local `mcp-remote` dev path is established here so subsequent tool work can be exercised against Claude Desktop and the MCP Inspector throughout.

**Exit criteria for E08:** The server starts locally and deploys to a Workers preview; the MCP Inspector connects over Streamable HTTP; the driver spike is concluded and recorded; a read-only-enforced read against Supabase succeeds from the edge runtime (and a write attempt is provably rejected); CORS preflight succeeds from a test browser origin; the auth checkpoint rejects an untokened request and admits a valid one; the secret is in Workers Secrets, not committed; the Shape C envelope type compiles and round-trips a hand-constructed fixture; `mcp-server/` imports nothing from `ingestion/` (verified). No `any` types in serving TypeScript. (Any internal health check used here is not registered as a public MCP tool, so UAT criterion #1's "exactly five tools" holds.)

### E09 — Regulation-stack tools

**Outcome:** `get_regulations`, `list_seasons`, and `get_tag_requirements` are implemented against the Montana corpus. `get_regulations` returns the full Shape C envelope with correct coverage signals; `list_seasons` and `get_tag_requirements` return their structured shapes with `sources[]`. Confidence and verbatim rule text pass through faithfully (ADR-008, ADR-017).

**Why third, and grouped:** These three share the most query and join logic — they all read the regulation/season/license/draw-spec stack through `jurisdiction_binding` fan-out. Building them together lets the join and coverage-signal logic be designed once. `get_regulations` is the flagship composite that proves the whole pattern; the other two are narrower reads over the same tables.

**Exit criteria for E09:** Each tool returns a spec-valid response (validating against its declared `outputSchema`, with `structuredContent` as the source of truth and read-only annotations set) for a representative Montana query, and a structured `coverage: "none"` response for an out-of-scope query; A/B license asymmetry and region-specific reporting are observable in `get_regulations`; every response carries `sources[]`; a row with an unsupported `schema_version` is excluded and surfaced in `meta.warnings` (not silently dropped, not a hard error); each tool resolves in a bounded number of DB round-trips (target: one query) with no per-binding query fan-out (Workers CPU/subrequest budget), validated on the largest MT district; per-tool happy-path and missing-data-path tests pass.

### E10 — Spatial and contact tools

**Outcome:** `check_land_status` (PostGIS point-in-polygon against `geometry` + `jurisdiction_binding` overlays — restricted areas, no-hunt zones) and `get_agency_contacts` are implemented. `get_agency_contacts` first requires sourcing/loading the hand-curated agency-contacts CSV (Q9) for MT (and CO) — net-new M3 data work that lands in this epic. These are the two differently-shaped tools: one spatial, one a contacts lookup.

**Why fourth, and grouped:** They share neither the regulation-stack join logic (E09) nor each other's shape, but both are smaller and self-contained. Grouping them keeps E09 focused on the composite-read pattern and isolates the spatial-query and contacts-lookup concerns.

**Exit criteria for E10:** `check_land_status` returns correct results for three cases — a point inside a true closure (`no_hunt_zone`), a point inside a regulated-but-huntable `other_overlay` (the AFA-type case, rendered as restricted-access not closed), and an unrestricted point; the spatial SQL carries the explicit `state` filter discipline established in ingestion (no cross-state fan-out); the agency-contacts CSV is sourced and loaded; `get_agency_contacts` returns the contact records for a point's district; per-tool happy-path and missing-data-path tests pass.

### E11 — Productionization and deployment

**Outcome:** The auth seam is finalized at V1 depth (static bearer-token checkpoint, OAuth-2.1-ready upgrade path); external error capture is integrated through one integration point — `@sentry/cloudflare` or Cloudflare Workers Observability (the workerd-compatible options; the Node Sentry SDK does not run on workerd) — behind a top-level Worker error boundary so transport-layer and tool-layer throws are both captured; the server is deployed to a reachable HTTPS endpoint on Cloudflare Workers; `mcp-server/README.md` documents each tool's shape with worked examples and the local-dev `mcp-remote` flow; an example client config snippet (for `claude_desktop_config.json` / `.mcp.json`, invoking `mcp-remote` against the deployed URL) is committed at repo root; the M3 UAT runbook is produced (mirroring the M1/M2 UAT pattern); and the M3→M4 handoff is written.

**Why last:** Hardening, auth, deployment, error capture, and documentation are most efficient once all five tools exist and their shapes are stable. The UAT runbook and handoff close the milestone.

**Exit criteria for E11:** The deployed server passes the M3 UAT criteria below; the auth gate rejects an untokened request and admits a valid one; an induced error surfaces in the external capture service within 60s via the top-level error boundary; the README and the committed example client-config snippet let a fresh client connect; the M3→M4 handoff document lands; the `m3` tag is pushed.

### Why sequential

E07 → E08 → E09 → E10 → E11 has one hard dependency chain and one isolation ordering:

- **E09 and E10 depend on E08 (hard).** Every tool reads through E08's transport + DB access layer + response envelope. Tools cannot be built before the foundation exists.
- **E11 depends on E09 + E10 (hard).** Productionization (auth finalization, deployment hardening, README with worked examples per tool, UAT) requires the full tool surface to exist and be shape-stable.
- **E07 is independent of E08–E11 (isolation, not dependency).** E07 is Python ingestion hygiene; it shares no code with the serving stack. It is sequenced first for operator-discipline reasons (close ingestion carry-forward before serving work, and accept the edge-runtime Postgres access *principle* via the ADR-003 amendment ahead of E08's driver-selection spike), but it could in principle run in parallel with E08 if capacity allowed. The PM holds the line on sequential planning regardless, to keep epic context clean.

## Success criteria for the milestone (UAT level)

M3 is done when the following can be verified by hand or by script (M3 UAT runbook drafted at the end of E11, following the M1/M2 UAT pattern). Unless noted, criteria target the **Montana** corpus; Colorado equivalents are spot-checked once `m2` has landed and are marked N/A-until-m2 otherwise.

1. The deployed remote server responds to an MCP `initialize` + `tools/list` over the Streamable HTTP transport and lists exactly the five V1 tools. The MCP Inspector (or an equivalent remote MCP client) connects to the deployed HTTPS endpoint and enumerates the tools.
2. `get_regulations(lat, lng, species, date)` for a coordinate inside a known Montana hunting district, a V1 species, and an in-season date returns a Shape C envelope with: a non-null `resolved.jurisdiction`, at least one `seasons.windows` entry, at least one `tags.tags` entry, a populated `sources[]`, and `meta.coverage.overall = "full"`. Verbatim rule text matches the loaded `verbatim_rule` byte-for-byte (ADR-008).
3. `get_regulations` for an out-of-scope species or a coordinate outside coverage returns a structurally identical envelope with the appropriate sections `null` and `meta.coverage` carrying `"none"` — not a silent empty result, not an error.
4. `list_seasons(state, species, year)` returns the loaded `season_definition` rows (PDF faithfulness was already UAT'd in M1/M2; this tests the serving layer against loaded data) for a representative **Montana** state/species/year as structured `ResolvedSeasonWindow` rows with `sources[]`.
5. `get_tag_requirements(state, species, year, residency)` returns the tag type(s), draw vs. general status, application deadline(s), and embedded `draw_spec` context for a representative **Montana** draw hunt, with `sources[]`. (**N/A until `m2`:** for a Colorado preference-point hunt, the embedded `draw_spec` shows `point_system.kind='preference_linear'` and a populated `pools: AllocationPool[]`.)
6. `check_land_status(lat, lng)` returns: for a point inside a true closure (`no_hunt_zone`), the overlay and its closure; for a point inside a regulated-but-huntable `other_overlay` (the AFA-type case), restricted-access — *not* "closed"; for an unrestricted point, a structured "no restriction" result. The spatial query carries the explicit `state` filter (no cross-state fan-out).
7. `get_agency_contacts(lat, lng)` returns the regional warden / rules hotline / regional office for the district containing the point, each with a `source`.
8. Every tool response carries a `sources` array; no tool returns regulation content without at least one source citation (ADR-001).
9. An untokened request to the deployed server is rejected at the auth gate; a request bearing a valid V1 bearer token is admitted. (V1 depth — full OAuth 2.1 authorization-code is not required for M3 sign-off.)
10. An induced server error appears in the external error-capture service within 60s, routed through the single top-level integration point.
11. `mcp-server/` contains no import from `ingestion/` and requires no Python to build, test, or run (ADR-003, ADR-005). No `any` types in serving TypeScript.
12. A fresh MCP client (Claude Desktop via `mcp-remote`, or a remote MCP client pointed at the HTTPS endpoint) can connect using the committed example client-config snippet / README instructions and successfully invoke `get_regulations`.
13. The Montana and Colorado ingestion data is unchanged — row counts in Postgres match the `m1` / `m2` baselines; M3 wrote no regulation data. (The hand-curated agency-contacts CSV loaded in E10 is the one permitted addition, per the In-scope carve-out.)
14. A row carrying an unsupported `schema_version` is excluded from tool output and surfaced as a `meta.warnings` entry — not silently dropped and not a hard error (tested with a synthetic out-of-range version).
15. Each tool returns `structuredContent` that validates against its declared `outputSchema`, and carries the read-only MCP annotations (`readOnlyHint`, `idempotentHint`); the `content[0].text` markdown is present as a derivative, not the source of truth.

## Known risks and mitigations

**R0 — Roadmap divergence and new ADRs.** M3 takes a posture (remote Streamable HTTP on Cloudflare Workers, OAuth-ready auth seam) that the roadmap did not originally specify, and it amends ADR-003. Treat the supporting ADRs (deployment posture, ADR-003 amendment, auth posture) as routine, expected M3 work rather than exceptional. The roadmap M3 section is updated to match before E08 begins, with human sign-off. This umbrella exists so a reader scanning for "where does M3 deviate from the roadmap?" sees one signal.

**R1 — Edge-runtime Postgres access (ADR-003 amendment).** The Workers runtime is not Node; the existing `mcp-server/` scaffold's direct `pg` pool assumption does not hold. Mitigation: an E08 spike decides between Cloudflare Hyperdrive (edge pooling + optional caching) and the Supabase serverless/HTTP driver; access is read-only by enforcement (a dedicated SELECT-only Postgres role, *not* the write-capable service-role key) so a serving-path defect cannot mutate data. PostGIS `ST_*` execution is unaffected — it runs in Postgres; only the connection mechanism changes. **Caching caveat:** Hyperdrive query-caching trades against regulatory freshness, which is a correctness property (ADR-001 / `meta.freshness`); V1 runs caching off or short-TTL, with a cache purge in the re-ingestion/deploy runbook. The ADR-003 amendment records the principle (E07); the driver + caching choice is the E08 spike's addendum.

**R2 — New-platform learning curve (Cloudflare Workers + Durable Objects + Wrangler + KV).** open-questions.md (Q6) cautioned against adopting a second unfamiliar platform alongside Supabase. Mitigation: start from the Cloudflare remote-MCP template (`remote-mcp-authless` / `remote-mcp-github-oauth`), which scaffolds the transport, OAuth provider, and KV wiring; prefer the stateless `createMcpHandler` path unless per-session state proves necessary (it likely does not — HuntReady tools are stateless reads), which avoids Durable Objects entirely for V1.

**R3 — Auth depth vs. GTM uncertainty.** The production auth model is GTM-determined and TBD. Building too much auth now risks rework when the GTM strategy lands; building too little undershoots the authenticated-MCP goal. Mitigation: the V1 decision is "auth-ready/minimal" — ship a static bearer-token checkpoint behind a single auth seam so the full OAuth 2.1 flow (via `@cloudflare/workers-oauth-provider`) drops in later. On public data the V1 gate's purpose is metering/abuse-control, not authorization; the full model is an explicit deferred open question, not an M3 deliverable.

**R4 — Response-shape fidelity to ADR-011.** The Shape C envelope is intricate (always-present null-bearing sections, coverage tri-state, plural tags/reporting, embedded `draw_spec`, warning codes). A tool that omits a key instead of returning `null`, or collapses "not applicable" into "not covered," breaks the contract. Mitigation: a response-shape conformance validator (the E08–E11 validation triad's dedicated reviewer) checks every tool against the `GetRegulationsResponse` / section interfaces in `architecture.md`; missing-data-path tests assert the null-bearing shape explicitly.

**R5 — Coverage signal correctness.** Distinguishing "not applicable" (`null` section) from "not in dataset" (`coverage: "none"`) is the heart of Shape C's value and easy to get subtly wrong, especially at jurisdiction/species resolution boundaries. Mitigation: success criteria #2 and #3 test both paths against real data; the validator treats coverage-signal logic as a first-class review surface.

**R6 — Verbatim and confidence pass-through.** The server must surface `verbatim_rule` byte-identically (ADR-008) and confidence consistently across MT and CO (ADR-017 FINALIZE). A normalization or re-derivation at the serving layer would silently break authority preservation. Mitigation: the source-faithfulness reviewer in the serving triad checks for any text transformation; success criterion #2 asserts byte-identity.

**R7 — Parallel-with-M2 data drift.** M3 develops against the Montana corpus while M2 finishes Colorado. A tool tested only against MT might mis-handle CO-specific shapes (preference-point draw_spec, GMU jurisdiction codes, no-hunt-zone overlays) that land later. Mitigation: build tools schema-generically (no MT-specific branches — the same discipline ADR-005/ADR-007 impose on ingestion); spot-check against CO as soon as `m2` lands; mark CO-dependent UAT criteria N/A-until-m2 rather than skipping the consideration.

**R8 — Deployment / cold-start / cost for a demo-able service.** A deployed remote server must be reachable and responsive for an interview demo. Mitigation: Cloudflare Workers have no cold-start sleep (unlike free-tier Render); hibernation only applies to idle Durable Objects, which the stateless path avoids. Validate reachability and latency in E11 UAT.

**R9 — Spec churn (2025-11-25 → 2026-07-28).** The MCP spec finalizes a new revision ~5 weeks after this PRD. Building against 2025-11-25 risks minor drift. Mitigation: build stateless (no `Mcp-Session-Id` reliance), which is the direction 2026-07-28 takes; isolate transport/protocol-version handling behind the SDK so a spec bump is an SDK upgrade, not a rewrite.

## Decisions already made

Load-bearing decisions the PM agent and implementation agents treat as fixed and reference rather than re-derive:

- **MCP server is the canonical interface.** ADR-002. Web and plugin are future clients; nothing bypasses the server to the DB.
- **Remote Streamable HTTP transport on Cloudflare Workers** is the M3 posture (this PRD § "The posture decision"). stdio is retained for local dev via `mcp-remote` only.
- **Auth is OAuth-2.1-ready but minimal for V1** — a static bearer-token / API-key checkpoint whose purpose on public data is metering/abuse-control; the full OAuth flow (via `@cloudflare/workers-oauth-provider`) is the documented upgrade path. The full GTM-determined model is deferred.
- **Postgres is reached from the edge runtime** via Hyperdrive or the Supabase serverless driver (ADR-003 amendment; driver chosen by the E08 spike). Read-only by enforcement (a dedicated SELECT-only role, not the write-capable service-role key).
- **Shape C response envelope.** ADR-011. Always-present null-bearing sections; tri-state coverage; `sources[]` everywhere.
- **Server returns structure; clients compose presentation.** ADR-013. No server-composed `overview`/`headline`.
- **Verbatim text, unaltered, with source citation on every response.** ADR-001, ADR-008.
- **Confidence surfaced consistently across states.** ADR-017 FINALIZE; the server does not re-calibrate.
- **Schema-version gating.** ADR-006. The server rejects unsupported `schema_version`.
- **The serving stack never imports from `ingestion/`.** ADR-003, ADR-005. No Python in `mcp-server/`.
- **No `any` types in serving TypeScript.** Architecture constraint.
- **Five V1 tools, no more.** The tool surface is fixed at the five named in `architecture.md`; "fewer, well-designed tools" over a thin wrapper around the whole schema (the remote-MCP best practice).
- **Q5 resolved — no BFF in V1.** Tools return pre-composited responses from SQL; the web app composes client-side in M4. (See below.)
- **Q6 resolved — Cloudflare Workers.** (See below.)
- **Q21 resolved — pin-enforce (option (a)), in E07.** (See below.)

## Open decisions resolved during M3

Resolved by or during M3:

- **Q5 (web BFF vs. HTTP shim) → no BFF.** With Postgres as the storage layer and Shape C composing the full regulatory stack in a single `get_regulations` SQL pass, the web app (M4) calls the MCP server / its Streamable HTTP transport directly and composites client-side. No BFF in V1. Resolution home: a note in the architecture doc and the new deployment-posture ADR; no separate ADR for Q5 itself.
- **Q6 (deployment target) → Cloudflare Workers.** Driven by the remote-MCP posture and production intent (a managed-OAuth *upgrade path*, edge autoscale, native WAF/rate-limiting, no cold-start sleep). Cloudflare Workers was *not* among Q6's original options (Railway/Fly/Render/Vercel); the remote-MCP posture changed the decision frame, which is why a platform outside the original set is selected. Resolution home: the deployment-posture ADR + README deployment section.
- **Q21 (PAD-US fetch-time pin-enforcement) → option (a), implemented in E07.** Production intent makes dev/prod snapshot parity a real correctness concern; the two-gates model is adopted for geometry fetches. Resolution home: the geometry-fetch hardening lands in E07 with a pitfall entry; the open-questions entry is retired referencing the E07 closure.

Newly surfaced, deferred past M3:

- **GTM-determined production auth model (new open question).** The IdP choice, scope design, API-key / B2B tiering, rate-limit policy, and any monetization/metering are determined by go-to-market strategy and are explicitly out of M3. M3 ships the seam at minimal depth. Trigger to resolve: a production go-decision (e.g., post-OnX) and a GTM strategy. This is added to `docs/open-questions.md` rather than decided here.

Not resolved during M3; remain open for later:

- **Q7 (plugin MCP client reuse).** M5.
- **Q8 (one schema or three).** Unchanged; sync-by-discipline holds through V1.
- **Q14 (Supabase publishable/secret key migration).** The serving stack's read-only DB connection should adopt the current key format during E08; whether that closes Q14 or just advances it is an E08 finding. (Q14's other half — the E01 RLS-verification runbook's legacy-key curl steps — is an ingestion/verification concern untouched by M3 and stays open.)

## Handoffs

### What M3 inherits from M1 + M2

(Enumerated in full in PRD 002 § "What M3 inherits from M1 + M2"; restated here for locatability.) Two states' regulation + geometry data queryable from Postgres behind deny-all RLS; a source-citation discipline (ADR-001) every tool response honors; a confidence calibration (ADR-017 FINALIZE) that means the same thing across MT and CO; the six-entity decomposed model (ADR-010) and the Shape C contract (ADR-011) reflected in the TypeScript types under `mcp-server/src/types/`; and PostGIS at the `extensions` schema (all `ST_*` calls `extensions.`-prefixed). M3 builds against the Montana corpus (frozen at `m1`) and inherits Colorado automatically as `m2` lands.

### What M4 inherits from M3

- A deployed, reachable remote MCP server exposing the five V1 tools over Streamable HTTP, with `sources[]` on every response. M4's web companion is a client of this server (ADR-002) — no BFF (Q5 resolved), composing client-side.
- An auth seam M4's web client authenticates against at the V1 depth, ready to deepen when the GTM auth model lands.
- An error-capture integration M4 reuses (same provider) so client-side and server-side errors are visible together (roadmap M4 deliverable).
- A stable Shape C contract reflected in the TypeScript types under `mcp-server/src/types/`. M4 composes presentation from structure it does not have to reshape.
- A documented deployment pattern (Cloudflare Workers) and the example client-config snippet M4's deployment config builds alongside.

### What M5 inherits from M3

- A canonical MCP server the `regulation-lookup` skill targets. Q7 (plugin client reuse) is decided in M5 against this server; the likely resolution (Claude Code registers the remote server directly) is lighter precisely because the server is already remote and spec-conformant.

### What the `m3` tag signals

`m3` on the commit where M3 UAT passes. It is the authoritative marker that the canonical interface is live: the five V1 tools are deployed, source-cited, spec-conformant, and reachable by any MCP-capable client. Everything tagged `m3` or later can assume an agentic client can hold a grounded conversation about Montana hunting (and Colorado, once `m2` has landed) against a deployed server.

## Non-goals beyond out-of-scope

Things the milestone is not optimizing for:

- **Not optimizing query performance beyond sane defaults.** Hyperdrive caching and schema indexes are used; tuning is V2.
- **Not designing the rate-limit / quota policy.** Edge rate-limiting is available at defaults; the policy is GTM-adjacent and deferred.
- **Not building multi-tenancy, user accounts, or per-user data.** The data is public; there is no resource owner to model in V1.
- **Not retrofitting new serving patterns into ingestion.** The language boundary holds; no Python is touched except E07's named items.
- **Not producing external-consumer / API documentation beyond the README's tool shapes and worked examples.** Full API docs are a GTM/V2 concern.

## What changes after this PRD

The following artifacts update as M3 progresses:

- `docs/roadmap.md` — the M3 section is evolved to the remote-MCP posture (with human sign-off) before E08 begins; the M3→M4 dependency note is updated to reflect that the MCP server is deployed in M3.
- `docs/planning/epics/` gains five epic files (E07–E11) as each epic is planned.
- `docs/planning/README.md` updates to reflect M3 progress.
- `docs/adrs/` gains new ADRs (ADR-023 onward): the remote-MCP deployment posture, the ADR-003 amendment for edge-runtime Postgres access, and the V1 auth-posture ADR. ADRs are drafted by the human or an explicit ADR-drafting session, not by the PM.
- `docs/open-questions.md` removes Q5/Q6/Q21 (resolved here) and adds the GTM-determined production-auth question.
- `docs/architecture.md` gains addenda for the serving deployment posture (transport, Workers, edge Postgres access) and the no-BFF resolution.
- `CLAUDE.md` updates with M3 status as the milestone progresses.
- `CHANGELOG.md` accumulates M3 entries as stories merge.

This PRD itself does not typically update during M3 execution. If M3 scope changes materially (e.g., a spike reveals the edge-Postgres path is unworkable and the posture must change), this PRD updates with human approval. Edits are tracked by commit history; no revision metadata block is needed.
