# Open Questions

This document tracks decisions that have not yet been made. Each open question names what is undecided, why it matters, what options are on the table, and what would move it to a decision. When a question is resolved, it is promoted to an ADR (or, if smaller, a note in `context.md` or `architecture.md`) and removed from this document.

This is a *working* document. It is expected to grow during the build and shrink through resolution. If it stops changing, that probably means work has stopped, not that the project has stabilized.

## Status key

- **Open** — undecided, not blocking current work.
- **Blocking** — must be resolved before the relevant milestone can proceed.
- **Parking lot** — not relevant until V2 or later; captured so it is not lost.

---

## Recently resolved

Questions resolved through the April 2026 research cycle. Listed here as visible handoff context during active work on M1 and M2; retire when the linked ADRs are sufficiently referenced elsewhere that this section is no longer useful for context. Full resolutions live in the linked research documents, in `architecture.md` / `research/schema-proposal-v2.md`, and in the ADRs linked under each question.

### Q1. How are Montana's big game regulations actually structured in the source PDF?

**Resolution:** Hybrid ingestion strategy. Geometries come from the MT FWP ArcGIS MapServer (`admbnd/huntingDistricts`, 40 layers including the V1 big-game layers). Regulation text, seasons, methods, and tag mechanics come from three published PDFs (DEA biennial booklet, Black Bear annual booklet, Legal Descriptions biennial booklet) plus ad-hoc correction PDFs. The `myfwp.mt.gov` undocumented endpoints are explicitly out of scope.

**Load-bearing discoveries for the schema:** (a) multiple named seasons per license row (Early / Archery Only / General / Heritage Muzzleloader / Late), (b) A-license vs B-license split with independent quotas, (c) closure predicates expressed as prose outside the table, (d) correction PDFs as a first-class publication type, (e) BMUs, HDs, and CWD Management Zones as three distinct geometry layers with overlay relationships, (f) region-specific reporting obligations within a species, (g) landowner preference as a quota sub-pool predicate.

**Sources:** [`research/montana-source-structure-findings.md`](research/montana-source-structure-findings.md), [`research/montana-gis-endpoints-verified.md`](research/montana-gis-endpoints-verified.md). All nine schema pressure points are addressed by the v2 entity model in [`research/schema-proposal-v2.md`](research/schema-proposal-v2.md).

**Resolution home:** [ADR-010](adrs/ADR-010-decomposed-entity-model.md) records the entity decomposition these discoveries drove.

---

### Q2. What is the minimum viable `get_regulations` response shape?

**Resolution:** Shape C — structured envelope with always-present, null-bearing sections and explicit coverage signals. Sections that don't apply carry `null` rather than being omitted; this distinguishes "not applicable" from "not in our dataset" explicitly rather than collapsing both to absence. The server returns structure; clients compose presentation (no server-side `overview` field).

**Divergences from the Q2 analyst's recommendation:** (a) `overview` dropped — clients compose their own headlines from structured sections, (b) `tags` pluralized to `tags: ResolvedTag[]` to accommodate Montana's A/B license pattern, (c) `reporting` pluralized to `obligations: ResolvedReportingObligation[]` for region-specific variance, (d) `closure_predicate` inline on `ResolvedSeasonWindow`, (e) `SUPERSEDED_BY_CORRECTION` warning code added.

**Sources:** [`research/mcp-tool-response-shape-recommendation.md`](research/mcp-tool-response-shape-recommendation.md), [`research/mcp_response_shape_analysis.md`](research/mcp_response_shape_analysis.md), [`research/response-shape-analysis.md`](research/response-shape-analysis.md). The committed response shape is `GetRegulationsResponse` in `architecture.md`.

**Resolution home:** [ADR-011](adrs/ADR-011-shape-c-response-envelope.md) records the Shape C commitment; [ADR-013](adrs/ADR-013-server-returns-structure-client-composes-presentation.md) records the "no server-composed `overview`" principle that followed from it.

---

### Q3. How is Colorado's preference-point draw system modeled in the schema?

**Resolution:** Sibling `draw_spec` entity with composite primary key `(state, hunt_code, year)`, referenced from `license_tag` by key. Draw mechanics are modeled as a `point_system` (null for no-points states like New Mexico), a `residency_cap` (null when residency is encoded per-pool), a `choices` config, and a list of `allocation_pool` objects — each pool having a share, a selection algorithm (enumerated: `rank_ordered_by_points` / `unweighted_random` / `squared_weighted_random` / `linear_weighted_random`), and an eligibility predicate. State-specific quirks (Utah youth allocation, Wyoming tier pricing, CPW moose exponential weighting) live in a typed `parameters` escape hatch that shared code does NOT read.

**Verified against:** Colorado's 80/20 hybrid, Wyoming's 75/25 split with 2-year inactive forfeit, New Mexico's three statutory pools with no points, Utah's squared bonus system. All four serialize cleanly with no state-specific branches in shared code.

**Sources:** [`research/colorado-draw-schema-proposal.md`](research/colorado-draw-schema-proposal.md). The committed schema is in `architecture.md` (entity: `DrawSpec`) and reasoning is in [`research/schema-proposal-v2.md`](research/schema-proposal-v2.md).

**Resolution home:** [ADR-012](adrs/ADR-012-draw-mechanics-sibling-entity.md) records the sibling-entity draw model.

---

### Q4. Are Colorado's unit boundaries available in a format we can use directly?

**Resolution:** Primary source is the CPW ArcGIS FeatureServer at `services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer/6` — layer 6, 186 big-game GMU polygons, `outSR=4326` server-side reprojection, no authentication required. Fallback is the Shapefile export from the Colorado Geospatial Portal (`geodata.colorado.gov`). Licensing is implicit under Colorado's Open Records Act; a hygiene email to CPW GIS staff before production launch is documented but does not block ingestion.

**Schema consequence:** unit geometries use `geography(MultiPolygon, 4326)` (not `Polygon`) because CPW data — and Montana HDs — include legitimate multi-part units along state lines.

**Sources:** [`research/gmu-source-evaluation.md`](research/gmu-source-evaluation.md). Ingestion details live in `ingestion/states/colorado/sources.yaml` when M2 begins.

**Resolution home:** No dedicated ADR; the `geography(MultiPolygon, 4326)` schema consequence is captured in [ADR-010](adrs/ADR-010-decomposed-entity-model.md), and the CPW source choice is an ingestion detail rather than an architectural decision.

---

## Blocking M1 (surfaced by schema-v2 proposal)

### Q11. How is `confidence` calibrated across state adapters?

**Why it matters:** Every entity in the v2 schema carries a `confidence: "high" | "medium" | "low"` field assigned by the ingestion pipeline. The field is user-facing — it appears in `ResolvedTag`, `ResolvedSeasonWindow`, `ResolvedReportingObligation`, and on every verbatim rule — and it gates warnings in the response (`LOW_CONFIDENCE`). If Montana's adapter calibrates differently from Colorado's, the field degrades from signal to noise: a `medium` in one state means something different than a `medium` in another, and the user has no way to know.

**Options:**
- Define shared calibration criteria in `ingestion/lib/schema.py` (e.g., `high` = extracted from structured table with 100% column match; `medium` = LLM-assisted extraction with validation against verbatim text; `low` = prose extraction without structural anchor). All adapters conform.
- Let each adapter define its own calibration, document the calibration per-adapter, and surface the calibration source in the response (e.g., `confidence_source: "mt-adapter-v1"`). Users comparing across states see that the calibration differs.
- Drop `confidence` as a user-facing field; keep it internal to the ingestion pipeline for QA only.

**What moves this to a decision:** the first Montana ingestion run with real variance in extraction quality. Until we see what `confidence` levels actually produce in practice, we cannot calibrate them meaningfully.

**Resolution home:** an ADR on confidence calibration once real data is in hand. Likely resolves as option 1 with explicit examples per level.

---

## Blocking M4

### Q5. Does the web companion need its own lightweight BFF, or is the MCP HTTP shim enough?

**Why it matters:** The architecture commits to the MCP server as canonical, with an HTTP shim for the web app. But if the web app's query patterns diverge meaningfully from the MCP tool shape (e.g., it wants composite responses that combine several tools' outputs), a thin BFF in front of the shim may be worth it. The wrong answer here is building a BFF too early, which invites duplicating logic from the MCP server.

**Options:**
- Web calls the HTTP shim directly; composites are done client-side.
- Web calls a thin BFF in `web/api/`, which composites MCP tools server-side and returns render-ready payloads.
- Web calls the HTTP shim directly in V1, and BFF is a V2 decision.

**What moves this to a decision:** the first real implementation of the regulation panel. If it feels natural to call 2–3 tools and composite client-side, option 1 is fine. If it feels awkward, option 2 is probably right.

With Postgres as the storage layer, the tools can return richer, pre-composited responses directly from SQL — a single `get_regulations` call can return the full regulatory stack rather than the web app having to stitch together several tool responses. This biases the resolution toward option 1 (no BFF needed in V1) because the composition happens at the query layer, not at the application layer.

**Resolution home:** an ADR if option 2 is chosen. Option 1 or 3 resolves quietly.

---

### Q6. What is the deployment target for the MCP server's HTTP shim?

**Why it matters:** The web app deploys cleanly to Vercel. The database is on Supabase. The MCP server's HTTP shim is the remaining piece — a long-running Node process that reads from Supabase and serves HTTP. The choice has small but real implications for cold-start latency, cost, and operational complexity.

**Options:**
- Railway — simplest setup, likely fastest to ship.
- Fly.io — strong developer experience, generous free tier, geographic deployment. Unfamiliar to this builder.
- Render — free tier sleeps, which is a problem for interview demos.
- Deploy to Vercel as a long-running route — viable but awkward for the MCP server specifically.

**What moves this to a decision:** probably preference. No strong architectural case for one over the others at V1 scale. The Supabase decision narrows the learning-curve tolerance; don't adopt a second unfamiliar platform if Railway will ship.

**Resolution home:** a note in the README's deployment section. Not worth an ADR.

---

## Blocking M5

### Q7. Should the Claude Code plugin use the same TypeScript MCP client as the web companion?

**Why it matters:** The `regulation-lookup` skill needs to call HuntReady's MCP tools from inside a Claude Code session. If it uses the same client code as the web app, there is one place where MCP call logic lives. If it uses its own approach (e.g., shelling out to `mcp` CLI tooling), it is simpler but forks the call pattern.

**Options:**
- Share the TypeScript MCP client across `web/` and `plugin/`, extracted into a shared package in the monorepo.
- Let the plugin use its own simpler approach, accepting small duplication.
- Use the MCP protocol natively via Claude Code's existing MCP support, with the plugin just supplying context/triggers.

**What moves this to a decision:** assessing how Claude Code's MCP integration actually works in practice. If Claude Code can register HuntReady's MCP server directly (likely), the plugin skills may not need to implement MCP calling at all — they may just need to know the server is there and trigger on the right patterns.

**Resolution home:** an ADR on plugin architecture if it's non-obvious. Likely resolves as option 3, which is also the lightest.

---

## Open, not blocking

### Q8. Does HuntReady ship one schema or three?

**Why it matters:** The schema is now defined in three places: TypeScript (`mcp-server/src/types/regulation.ts`), Python (`ingestion/lib/schema.py`), and Postgres DDL (`supabase/migrations/`). Keeping three representations in sync manually is a real burden, and drift between any two can cause subtle correctness bugs — e.g., ingestion successfully validates a record that then fails at the Postgres insert, or the MCP server returns a shape the web app doesn't know how to render.

**Options:**
- Keep three definitions, sync by discipline. Viable at V1 scale; fragile at V2 scale.
- Define once in JSON Schema, generate TypeScript and Python types; treat Postgres DDL as a separate concern kept in sync by hand.
- Define once in Postgres DDL, generate TypeScript types via a tool like `postgres-meta` or `kysely-codegen`, generate Python types via a separate pipeline.
- Define once in TypeScript (Zod), generate a Python validator and Postgres DDL from a single source.

**What moves this to a decision:** the first time two of the three schemas drift in practice. If it doesn't happen during V1, the default is option 1 with explicit discipline in the ADRs. If it happens once, fix it by hand and log the incident. If it happens twice, promote this question and resolve it.

**Resolution home:** an ADR if unification is chosen, probably at V2. If option 1 holds through V1, no ADR is needed — the drift discipline is already captured in the architecture doc.

---

### Q12. How is `draw_spec.parameters` enforcement maintained?

**Why it matters:** The v2 schema's `draw_spec.parameters` field is a typed `Record<string, unknown>` explicitly not read by shared code (the MCP server, the response builder, the web client). State-specific quirks — Wyoming tier pricing, Utah youth allocation, CPW moose exponential weighting — live here. The discipline matters because if shared code starts reading `parameters`, the hard constraint (no state-specific branches in shared code) breaks silently. TypeScript cannot enforce this; any code *can* read the field. [ADR-012](adrs/ADR-012-draw-mechanics-sibling-entity.md) commits to the escape hatch; this question asks how the "shared code does not read it" discipline is maintained.

**Options:**
- Convention plus code review. At V1 scale with one contributor, this is sufficient and is the committed V1 answer.
- A lint rule (custom ESLint) that flags any `.parameters` access outside `ingestion/states/`.
- A runtime assertion in development mode that panics if a shared module touches `parameters`.
- Rename the field to `_state_adapter_parameters` or similar so the name itself signals the rule.

**What moves this to a decision:** contributor scale. At one contributor, convention holds. At 3+, something stronger is warranted. Not M1-blocking.

**Resolution home:** a note in `CONTRIBUTING.md` for V1; promoted to a lint rule if contributor count grows. Not an ADR unless convention fails.

---

### Q9. How are agency contact records maintained?

**Why it matters:** Agency contacts (regional wardens, regulation hotlines) are not reliably available via API. V1 hand-curates them into a CSV per state. This works at V1 scale; it does not work at V2 scale with ten states.

**Options:**
- Continue hand-curating.
- Scrape state agency websites for contact information.
- Use a third-party data provider.
- Partner directly with state agencies for authoritative contact data.

**What moves this to a decision:** scale. Not a V1 decision.

**Resolution home:** a V2 ADR on data-maintenance strategy.

---

### Q10. Does the product name stay "HuntReady"?

**Why it matters:** "HuntReady" came from the original BirdDog-era product thinking. It is fine, but it is not the only option, and if the product has commercial legs beyond a portfolio artifact, the name is worth re-examining before it is engraved in partnerships, domain names, and an app store listing.

**Options:**
- Keep HuntReady.
- Rename at V1 complete, before any external commitments.
- Defer until V2.

**What moves this to a decision:** whether the product goes anywhere beyond the interview. Not a V1 decision.

**Resolution home:** not relevant to V1. Captured here so it isn't lost.

---

### Q13. When does HuntReady go public, and under what license, if ever?

**Why it matters:** V1 is a private repository shared only with intended evaluators (interview panel, potential collaborators). This is the right Phase 1 posture — it preserves commercial optionality, simplifies IP provenance for a future acquirer, and eliminates the risk of premature forking. But "private forever" is not a default; it is a decision that should be revisited when Phase 1 ends.

**Options (non-exclusive, path-dependent):**
- Stay private indefinitely as a portfolio artifact shared on request.
- Go public under a source-available license (Business Source License or Elastic License v2) if commercial intent is active.
- Go public under a permissive OSS license (MIT or Apache-2.0) if the product becomes a portfolio piece rather than a commercial product.
- Transfer to an acquirer who makes the visibility and license decision themselves.

**What moves this to a decision:** the outcome of the OnX interview process, and any commercial conversations that follow from it. No Phase 1 action required; this is explicitly a post-V1 question.

**Resolution home:** a `LICENSE` file and a note in the README when Phase 2 begins. An ADR if the decision has architectural implications (e.g., BSL's time-based conversion has downstream scheduling implications).

### Q14. How do Supabase's new publishable/secret API keys affect RLS verification and service-role access patterns?

**Why it matters:** Supabase has deprecated the legacy `anon` and `service_role` JWT keys in favor of new `sb_publishable_*` and `sb_secret_*` keys. HuntReady's RLS deny-all policies target the `anon` and `authenticated` PostgreSQL roles, which are unaffected at the database level. However, the E01 migration verification runbook (`docs/runbooks/E01-migration-verification.md`) uses legacy keys in curl commands to verify RLS behavior. If the legacy keys are removed, those verification steps break. Additionally, the MCP server and ingestion pipeline may need to adopt the new key format for Supabase client connections.

**What needs to be decided:**

1. Do the new keys still map to the same PostgreSQL roles (`anon`, `authenticated`, `service_role`) under the hood, or does Supabase's API layer handle authorization differently?
2. Should runbooks and `.env` templates migrate to the new key format now, or wait until Supabase removes legacy key support?
3. Does the MCP server's `SUPABASE_SECRET_KEY` (used for service-role bypass) need to change?

**Surfaced by:** E01 epic audit (2026-04-28). Observed in the Supabase dashboard — legacy keys are on a separate tab labeled "Legacy anon, service_role API keys."

**Resolution home:** Update to `architecture.md` storage section and `docs/runbooks/E01-migration-verification.md`. An ADR only if the new keys change the RLS enforcement model.

---

## Parking lot

### P1. Observability and error tracking

Sentry, Honeycomb, or similar for the MCP server and the web app. Not a V1 concern. Will matter the moment real users are on the system.

### P2. Ingestion provenance and audit trail

A production version of the ingestion pipeline should track not just *what* was ingested but *when*, *from where*, and *by what version of the extractor*. V1 carries `source_date` on every record, which is the minimum. Fuller provenance (git-committed source snapshots, checksums, etc.) is V2.

### P3. Handling emergency rule changes mid-season

State wildlife agencies issue emergency orders (e.g., CWD-related unit closures) mid-season. V1 ingests at build time and does not handle these. A production version needs a fast path for emergency-order ingestion and a user-facing indicator. Important but not V1.

### P4. Internationalization

Non-English speakers hunt in the U.S. Spanish in particular is relevant. V1 is English only. This is a real product concern for V2+.

### P5. Accessibility audit of the web companion

WCAG compliance is not a V1 deliverable but should be assessed before any serious consumer launch. The map-first UI has accessibility implications worth thinking about carefully.

---

## How to use this document

When working on the project:

- If you hit a decision point and this document contains it, resolve it per the "what moves this to a decision" note, then move the resolution to the appropriate home (ADR, context, architecture, README) and delete the entry here.
- If you hit a decision point and this document does not contain it, add it here before deciding. The decision and its reasoning are more valuable than the outcome.
- If the same question keeps recurring across sessions, it belongs as an ADR even if the decision is small.

The document is designed to be agent-friendly. A PM agent drafting epics should consult this document for known ambiguities. An implementation agent hitting a choice point should escalate back to this document rather than making a silent call. The goal is that decisions are made in one place and referenced everywhere, not rederived every session.
