# Open Questions

This document tracks decisions that have not yet been made. Each open question names what is undecided, why it matters, what options are on the table, and what would move it to a decision. When a question is resolved, it is promoted to an ADR (or, if smaller, a note in `context.md` or `architecture.md`) and removed from this document.

This is a *working* document. It is expected to grow during the build and shrink through resolution. If it stops changing, that probably means work has stopped, not that the project has stabilized.

## Status key

- **Open** — undecided, not blocking current work.
- **Blocking** — must be resolved before the relevant milestone can proceed.
- **Parking lot** — not relevant until V2 or later; captured so it is not lost.

---

## Recently resolved

Questions resolved during M1/M2 build cycles (initial batch from the April 2026 research cycle; subsequent additions from M2 mid-epic flag-and-discuss events as they close). Listed here as visible handoff context during active work; retire individual entries when the linked ADRs / closure memos are sufficiently referenced elsewhere that this section is no longer useful for context. Full resolutions live in the linked research documents, in `architecture.md` / `research/schema-proposal-v2.md`, in the ADRs linked under each question, and (for M2 mid-epic resolutions) in the per-story closure memos under `docs/planning/epics/E0X-confidence-findings/`.

### Q15. Where does section-level verbatim text live on `regulation_record`? (resolved 2026-05-14 during S03.6)

**Question:** S03.6's epic spec mapped DEA section `verbatim_text` and Black-Bear merged-row text onto `regulation_record.verbatim_rule` ([epic line 565](planning/epics/E03-regulation-text-ingestion.md)). During implementation discovery the column was found to not exist — the DDL (`supabase/migrations/20260425000000_initial_schema.sql:36-49`) and the Pydantic `RegulationRecord` model (`ingestion/ingestion/lib/schema.py:221-238`) both define an anchor entity with no `verbatim_rule` field. Three options were considered: (a) add the column via a new migration, (b) carry section text via an `additional_rules` discriminator, (c) drop section text from `regulation_record` and let it decompose into S03.7's per-entity verbatim fields.

**Decision:** Option (c). `regulation_record` stays a pure anchor: `(PK, source, confidence, schema_version, ingested_at) + additional_rules: VerbatimRule[]`. Section-level text decomposes onto the entities that scope it:

- Per-license-row text → `license_tag.verbatim_rule` (S03.7)
- Per-season-window text → `season_definition.verbatim_rule` (S03.7)
- HD-wide `NOTE:` lines → `regulation_record.additional_rules: VerbatimRule[]` (S03.6 captures these)

For bear specifically: the per-BMU prose decomposes into `season_definition.verbatim_rule` (S03.7, one row per general/archery/spring/hound-training window with `closure_predicate` populated for the quota-closure + female-sub-quota BMUs) and `license_tag.verbatim_rule` (S03.7, hound-NR license). The bear closure prose lives on `reporting_obligation.verbatim_rule` (S03.9).

**Rationale:** Storing section-level text on `regulation_record` would denormalize the same prose at multiple levels (section + per-row), inviting drift between the two stored copies and violating ADR-010's decomposition principle. ADR-008's verbatim-preservation invariant is satisfied because every reg-bearing piece is faithfully stored on the entity it describes; the artifact's full `verbatim_text` field remains in the JSON artifact (committed to repo) as a debug/audit aid. Option (a) would have required a migration with three-place sync (DDL + Pydantic + TS types); option (b) would have required a `VerbatimRule.kind` discriminator the schema doesn't currently model.

**Known risk:** Free prose between rows that isn't a `NOTE:` line currently has no structured home in the DB. V1 Montana DEA is dense table data + `NOTE:` lines; this is expected to be empty set. S03.12 UAT spot-checks; S03.6's working note flagged any encountered cases (working note deleted at m1 tag per ADR-017 §6; no cases were observed in V1 Montana).

**Resolution home:** No new ADR (this is a refinement of ADR-008's decomposition story, not a new commitment). Epic E03 line 565 amended with footnote `[^oq1]`. Plan: [`.roughly/plans/S03.6-regulation-record-ingestion-plan.md`](../.roughly/plans/S03.6-regulation-record-ingestion-plan.md). Working note (S03.6.md) deleted at m1 tag per ADR-017 §6; durable record lives in [`docs/planning/epics/E03-confidence-calibration-synthesis.md`](planning/epics/E03-confidence-calibration-synthesis.md).

---

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

### Q20. How are CPW "Season Choice" licenses modeled as `season_definition` / `license_tag` in S06.7? (resolved 2026-06-23 during S06.7 entry-time flag-and-discuss; closure memo durably records the decision)

**Question:** S06.3's CPW Big Game extraction surfaced "Season Choice" hunt codes (method letter `X`) — one license, valid for the hunter's choice among archery / muzzleloader / rifle sub-seasons. The extractor captured each row's 3 method-windows + `weapon_types=["archery", "muzzleloader", "any_legal_weapon"]` faithfully, but the schema has no "season choice" license/weapon type — the concept is *license flexibility*, not a weapon type. Three options for downstream entity shape: (a) per-window fan-out (one `season_definition` per method-window + one `license_tag` with weapon_types union), (b) single multi-weapon span with `weapon_type=None`, (c) skip X rows for V1.

**Decision:** Option (a) — **Per-window fan-out**. Each X hunt code → 3 `season_definition` rows (one per choosable method with own `weapon_type` + own date window verbatim) + 1 `license_tag` carrying weapon_types union + `license_season` links the tag to all 3 seasons. F-sex 0-window edge case: still create the `license_tag`, 0 `license_season` links, WARNING logged with `hunt_code + GMU + sex + list_value` for PM grep + spot-check.

**Rationale:** ADR-008 (verbatim/faithfulness) — Option (b) collapsing the 3 distinct windows into one span would mis-answer weapon-type-scoped hunter queries (e.g., "archery in GMU 091" would return the full Oct 1-Nov 3 span instead of the correct Oct 1-23). ADR-001 (authority preserved, not replaced) — Option (c) drops real regulatory data S06.3 specifically built extraction for. ADR-013 (server returns structure; client composes presentation) — clients render the 3 linked seasons however they want. Mirrors M1's existing pattern for non-X multi-method licenses. The "choose-one" semantic is a license-issuance-layer rule (one license = one harvest); no schema-level "choose-one" flag is required — `license_tag.weapon_types` = legal methods + `license_season` linking to multiple = "valid in any."

**Affected:** 6 CO deer `season_choice` sections in `big-game-2026.json` (`method_group="season_choice"`, `list_value="C"`); S06.7 produces ~18 new `season_definition` + ~6 new `license_tag` + ~18 new `license_season` rows from this fan-out (modulo F-sex 0-window skips).

**Resolution home:** No new ADR (refines ADR-008's verbatim-decomposition story, not a new commitment). Decision durably recorded in S06.7 closure memo at [`docs/planning/epics/E06-confidence-findings/S06.7.md`](planning/epics/E06-confidence-findings/S06.7.md) (deletes at `m2` tag per ADR-017 §6) + the E06 epic at [`epics/E06-colorado-regulation-text-ingestion.md`](planning/epics/E06-colorado-regulation-text-ingestion.md) § "S06.7 Status" closure block (durable through m2). PM commit `317fc3d` filed the resolution; S06.7 PR #75 / `433ea73` shipped the implementation 2026-06-24.

---

## Blocking M1 (surfaced by schema-v2 proposal)

### Q11. How is `confidence` calibrated across state adapters?

**Status (2026-05-27 via S03.11): RESOLVED.** ADR-017 (Confidence Calibration and Parent-Inheritance Rule) stands as-is. S03.11's stratified audit ran 50 rows across 10 documented edge cases against V1 Montana data: 39/39 = 100% pass-rate on `regulation_record.confidence` (the only entity with a confidence column per ADR-017 §3); 6/6 on EC8 closure_predicate parent-inheritance; 5/5 on EC9 license_tag row-level extraction_confidence. Final tier distribution across 437 projected `regulation_record` rows: `high=32, medium=405, low=0`. The user selected the INTENT reading of ADR-017 §7 Trigger 2 at amendment-review time (`low=0` is absence-by-data-property, not absence-by-framework-gap; the LOW rule exists, is unit-tested, and behaves correctly when its input conditions are present — V1 Montana data simply doesn't exercise it). PM's amendment DRAFT was rejected; the DRAFT file was deleted. Full audit and rationale: [`docs/planning/epics/E03-confidence-calibration-synthesis.md`](planning/epics/E03-confidence-calibration-synthesis.md) (survives past M1).

**Why it matters:** Every entity in the v2 schema carries a `confidence: "high" | "medium" | "low"` field assigned by the ingestion pipeline. The field is user-facing — it appears in `ResolvedTag`, `ResolvedSeasonWindow`, `ResolvedReportingObligation`, and on every verbatim rule — and it gates warnings in the response (`LOW_CONFIDENCE`). If Montana's adapter calibrates differently from Colorado's, the field degrades from signal to noise: a `medium` in one state means something different than a `medium` in another, and the user has no way to know.

**Options:**
- Define shared calibration criteria in `ingestion/lib/schema.py` (e.g., `high` = extracted from structured table with 100% column match; `medium` = LLM-assisted extraction with validation against verbatim text; `low` = prose extraction without structural anchor). All adapters conform.
- Let each adapter define its own calibration, document the calibration per-adapter, and surface the calibration source in the response (e.g., `confidence_source: "mt-adapter-v1"`). Users comparing across states see that the calibration differs.
- Drop `confidence` as a user-facing field; keep it internal to the ingestion pipeline for QA only.

**What moves this to a decision:** the first Montana ingestion run with real variance in extraction quality. Until we see what `confidence` levels actually produce in practice, we cannot calibrate them meaningfully.

**Resolution home:** an ADR on confidence calibration once real data is in hand. Likely resolves as option 1 with explicit examples per level.

---

## Blocking M4

> **Both questions in this section were RESOLVED 2026-06-24** (via PRD 003 / ADR-023). They are retained in place — each with a resolution note above its original framing — for handoff context, mirroring the in-place resolution of Q11 under "Blocking M1." The "Blocking M4" label is now historical: nothing in this section still blocks M4.

### Q5. Does the web companion need its own lightweight BFF, or is the MCP HTTP shim enough?

**Status (2026-06-24 via PRD 003 / M3 planning): RESOLVED — no BFF in V1.** With Postgres as the storage layer and Shape C composing the full regulatory stack in a single `get_regulations` SQL pass, the M4 web app calls the MCP server's Streamable HTTP transport directly and composites client-side (Q5 option 1). Consequence surfaced during resolution: the no-BFF decision makes CORS/preflight an M3 *server* concern (browser → Worker direct), folded into M3 scope. Resolution home: [ADR-023](adrs/ADR-023-remote-mcp-server-posture.md) + the architecture.md no-BFF addendum.

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

**Status (2026-06-24 via PRD 003 / M3 planning): RESOLVED — Cloudflare Workers.** The M3 posture shifted from a local stdio server + REST shim to a remote, deployed Streamable HTTP MCP server, which changed the decision frame: Cloudflare Workers (with the Agents-SDK remote-MCP toolchain, managed-OAuth upgrade path, edge autoscale, native WAF/rate-limiting, no cold-start sleep) is selected. Note Cloudflare Workers was *not* among this question's original options (Railway/Fly/Render/Vercel) — the remote-MCP posture is why a platform outside the original set is chosen. The Q6 caution against a second unfamiliar platform is addressed by PRD 003 R2 (start from Cloudflare's remote-MCP template; stateless `createMcpHandler`, no Durable Objects). Resolution home: [ADR-023](adrs/ADR-023-remote-mcp-server-posture.md) + the README deployment section.

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

**M3 note (2026-06-24):** the serving stack's read-only DB connection adopts the current key format during E08 (advances this question's serving half); the E01 RLS-verification-runbook half is untouched by M3 and stays open.

---

## Q16: Species granularity of license_tag and season_definition (S03.7 → M2 revisit)

**Story:** S03.7 (closed 2026-05-15)
**ADR-relevance:** ADR-010 (decomposed entity model), ADR-018 (license_season link table)
**Status:** Resolved for V1; flagged for M2 review.

S03.7 writes one `license_tag` (and one `season_definition`) per artifact-level species label (`"deer" | "elk" | "antelope" | "bear"`).  For DEA deer sections that fan out to DB species_group values `"mule_deer"` and `"whitetail"`, the fan-out happens only at the `regulation_license` / `regulation_season` link layer — both DB regulation_records reference the same shared license_tag / season_definition.

**Rationale:** A "Deer B License: 262-50" license is sold once and is valid for either species.  Duplicating the license_tag into a mule_deer variant + a whitetail variant would create false structural distinction; the link tables already express the species coverage correctly.

**M2 revisit trigger:** if Montana (or any other state) ever ships a species-specific license (e.g., mule-deer-only with no whitetail validity), the V1 shared-license_tag model wouldn't fit cleanly.  At that point, decide between:

- (a) Splitting the license_tag into per-species variants with disambiguated IDs.
- (b) Adding a `valid_species: list[str]` column on license_tag.
- (c) Some hybrid.

For now: no action; surface in M2 scoping.

---

## Q17: How should per-HD allocation caps be modeled in `draw_spec`?

**Status:** Open (M2 ADR-candidate)
**Surfaced by:** S03.8 (2026-05-18)
**Touches:** ADR-012 (`draw_spec` sibling entity), `draw_spec` schema

### The case

Some Montana DEA licenses are cross-listed across multiple HDs. The DEA booklet
prints a single license_code (e.g., `Elk B License: 210-03`) in multiple HD
sections, with one of those sections being the "home HD" carrying the total
drawable quota, and the others carrying per-HD allocation caps:

**Concrete example (DEA 2026 booklet):**

- HD 210 (home), p. 53 row 7 — `Elk B License: 210-03`, quota=300, range=5-1,000,
  detail="Valid on private lands in HDs 211, 212, 216 and south portion of 210
  (Rattling Gulch-Henderson Creek)."
- HD 211, p. 53 row 21 — same license, quota=200, **identical detail text**
- HD 212, p. 54 row 12 — same license, quota=200, identical detail
- HD 216, p. 57 row 13 — same license, quota=200, identical detail

The home-HD quota=300 is the total drawable count; the cross-listed quota=200
values are per-HD allocation caps on where those 300 licenses can be hunted.

### Why V1 can't model this

The current `draw_spec` schema (`AllocationPool[]`, `ChoiceConfig`,
`residency_cap`, `point_system`) has no field for per-HD allocation caps. The
`AllocationPool.eligibility` field carries `min_points`, `residency`, `guided`
— not jurisdiction-keyed allocation caps.

### V1 workaround (S03.8)

`_KNOWN_CROSS_LISTING_OVERRIDES` in `ingestion/states/montana/load_draw_specs.py`
records the canonical quota (300) explicitly. Cross-listed cap values (200) are
dropped from `draw_spec.quota` and logged as a WARN at run time. The home-HD
detail text is preserved in `license_tag.verbatim_rule` (via S03.7's section-
scoped fallback). This means consumers reading `draw_spec.quota=300` see the
drawable total, and consumers reading the per-HD `license_tag.verbatim_rule`
see the "Valid on private lands in HDs 211, 212, 216 and south portion of 210"
language — but the structured per-HD cap is invisible.

### M2 options to evaluate

1. **`draw_spec.parameters` (Q12 escape hatch)**: encode caps as
   `parameters["per_hd_caps"] = {"210": 100, "211": 200, ...}` — pragmatic but
   ADR-012 reserves `parameters` for state-adapter-only quirks; shared code
   (MCP server) cannot read it.

2. **New `draw_spec.per_hd_allocations` field**: jsonb column with structure
   `{jurisdiction_code: max_licenses}`. Promotes the cap from quirk to
   first-class. Requires schema migration + DDL update + type sync.

3. **Hunt-code disambiguation**: split into N distinct hunt_codes
   (`"Elk B License: 210-03/HD-210"`, `"Elk B License: 210-03/HD-211"`, etc.).
   Each gets its own draw_spec with its own quota. But these aren't separate
   licenses — they're allocations of the same license — so this would model
   them as if they were independent draws, which they aren't.

### Decision criteria for M2

- Are there other (non-Montana) states with similar per-HD-cap semantics?
  (Colorado / Wyoming research needed.)
- Does the MCP server's `get_tag_requirements` tool need per-HD-cap visibility
  for hunters checking which HD has remaining licenses?
- Does ADR-012's "parameters is state-adapter-only" stance accept per-HD-caps
  as a "Montana quirk" or are they a cross-state structural pattern that
  deserves first-class schema?

### Affected V1 entries

Currently exactly 1 (HD 210). M2 should re-survey when MT 2027 booklet ships
and when CO / WY data lands.

**Working note:** S03.8.md (deleted at m1 tag per ADR-017 §6); HD 210 cross-listing conflict captured in the deferred-items entry below.
**Deferred-items entry:** [`docs/planning/epics/E03-deferred-items/draw-mechanics.md`](planning/epics/E03-deferred-items/draw-mechanics.md) § "Per-HD allocation caps for cross-listed B licenses"

---

## Q18: Does `reporting_obligation` model per-zone CWD sampling rules in V1?

**Date opened:** 2026-05-20 (during S03.9 planning)
**Status (2026-06-08 via S06.0/D1): RESOLVED — option (c), license-keyed.** M2 (Colorado, the second CWD-state) confirmed zone-keyed binding is structurally unavailable (CPW publishes no CWD-zone geometry — E05 S05.3). CO V1 ships 0 typed `cwd_sample` `reporting_obligation` rows (empirically 1 total CO reporting_obligation — the bear mandatory-check — per S06.9); the `cwd_sample` enum stays defined-but-unused; CWD text lives in `regulation_record.additional_rules` (S06.6). No new table, no ADR. Resolution home: S06.0 decision memo (D1); recorded in the M2→M3 handoff §6. *(Prior status: Open — M2 ADR candidate; V1 disposition: defer.)*

### Options considered (resolved to (c) at S06.0/D1)

- **(a) Zone-keyed typed `reporting_obligation` rows** — one row per CWD zone, bound to geometry via `geometry-overlays.json`. **Rejected:** CPW publishes no CWD-zone geometry (E05 S05.3 — structurally unavailable for CO; there is no zone to key on), and even in MT the sampling mandate is license-keyed not zone-keyed (the `103-50` case in Context below).
- **(b) License-keyed typed `reporting_obligation` rows** — one typed `kind="cwd_sample"` row per sampling-bearing license. **Rejected for V1:** produces near-duplicate rows differing only in the zone-name token (the wrong row shape — see "Three sub-questions" #2), with an ambiguous `regulation_reporting` join key.
- **(c) Keep CWD-sampling text in `regulation_record.additional_rules`; 0 typed `reporting_obligation` rows** (the license-keyed disposition — the text attaches to the license-bearing `regulation_record`). **SELECTED.** The rules are already searchable from `additional_rules` after S03.6/S06.6; the only thing V1 forgoes is the typed `kind="cwd_sample"` discrimination (see "Three sub-questions" #3). CO empirically writes exactly 1 `reporting_obligation` (the bear mandatory-check, S06.9) and 0 CWD rows.

### Context

Montana V1 has 2 CWD zones (Kalispell, Libby). The 10-day-sampling sentence appears 5 times across 4 HDs (100/103/104/170) as per-license `extras` cells in `dea-2026.json`, already captured by S03.6 in `regulation_record.additional_rules`. The artifact pattern is **license-keyed**, not zone-keyed: HD 103's `Deer Permit: 103-50` (North Fisher Portion mule deer) carries the same sampling sentence, but that license is NOT inside the Libby CWD-zone overlap captured in `geometry-overlays.json`. The sampling mandate is bound to the LICENSE TYPE, not strictly geography.

### Three sub-questions

1. **Zone-keyed vs. license-keyed authority.** Joining `regulation_reporting` rows to `regulation_record` via CWD-zone-overlap from `geometry-overlays.json` would miss the `103-50` case. The license-keyed model is what's already in the artifact's per-row `extras`. If we promote CWD sampling to `reporting_obligation`, the join key from `regulation_reporting` is ambiguous.

2. **Verbatim source duplication.** Each of the 4 HDs repeats the SAME sentence (Kalispell or Libby zone variant). If we write `reporting_obligation` rows from this, we get 4-5 near-duplicate rows differing only in the zone-name token. That's faithful to ADR-008 but is the wrong row shape.

3. **What does V1 lose by deferring?** Per-HD CWD sampling rules ARE already in `regulation_record.additional_rules` after S03.6. Clients querying "what regulations apply to this HD?" already get the text. The only loss is the typed `kind="cwd_sample"` discrimination in `reporting_obligation`.

### S03.9 disposition

Ship 0 CWD-sampling `reporting_obligation` rows. Text is searchable via `regulation_record.additional_rules`. Revisit at M2 when Colorado lands a second CWD-state.

### What moves this to a decision

- Second CWD-state lands (Colorado) — confirms whether license-keyed vs. zone-keyed is a Montana quirk or a general pattern
- M2 client requirement: does a consumer need to query "what CWD-sampling rules apply?" as a typed reporting_obligation, or is `regulation_record.additional_rules` containing the sentence sufficient?

### 2026-06-03 evidence (S05.3 — Colorado, the second CWD-state)

Colorado's geometry ingestion (E05 S05.3) investigated CPW's CWD publications across all sources and found **CPW publishes no CWD-zone geometry at all** — no CPWAdminData layer (30 layers scanned), no ArcGIS Online service under the CPW org (~200-service listing scanned; org-scoped CWD search = 0), and no hand-traceable regulatory boundary. Colorado manages CWD by **hunt code / GMU** (2026: mandatory elk submission from specific rifle hunt codes, Big Game Brochure pp. 41–52; USGS reports CO CWD positives by wildlife-management-unit). This is the second-CWD-state trigger named above (line 376): it confirms the **license/unit-keyed model is the general pattern, not a Montana quirk** — and that zone-keyed binding is not merely awkward but **structurally unavailable** for Colorado (there is no zone to key on). Evidence strongly supports retaining the V1 license-keyed disposition; the formal Q18 decision remains E06's. Source: `ingestion/states/colorado/cwd-source-discovery.md`. **Status at the time of this 2026-06-03 note: Open** (V1 disposition: defer) — this note added evidence only; the formal decision was still E06's. **Q18 was subsequently RESOLVED at S06.0/D1 (option (c)) — see the status line + "Options considered" at the top of this entry.**

### Affected V1 entries

Currently 5 verbatim occurrences across 4 HDs (100/103/104/170) in `regulation_record.additional_rules`. The 103-50 case is the canonical zone-vs-license edge case.

**Working note:** S03.9.md (deleted at m1 tag per ADR-017 §6); the Probe 2 CWD sampling analysis is captured in the deferred-items entry below.
**Deferred-items entry:** [`docs/planning/epics/E03-deferred-items/cwd-sampling-modeling.md`](planning/epics/E03-deferred-items/cwd-sampling-modeling.md)

---

## Q19: Should `id text`-PK UPSERTs forbid updating slug-encoded fields to prevent silent semantic drift?

**Date opened:** 2026-05-21 (during S03.9 cubic-review round 3)
**Status (2026-05-29 via PR #45 `ccbe085`): RESOLVED.** Resolution per [ADR-020 — Derive-and-Assert for id text-PK Slug Drift](adrs/ADR-020-id-text-pk-slug-derivation.md) (Accepted). Option A adopted; Options B (no-update slug fields → orphan-link risk) and C (TRUNCATE before re-run → loses idempotency) explicitly rejected per ADR-020 § Alternatives. New shared module `ingestion/ingestion/lib/drift_guard.py` ships two primitives — `assert_dispatch_dict_drift_free` for compile-time dispatch dicts (the S03.9 case) and `assert_id_matches` for runtime row-construction (the S03.7 case). **Discovery-gate finding:** Q19's original framing below assumed all 3 affected helpers were compile-time dispatch dicts; discovery confirmed only `_REPORTING_ROW_SPEC` (S03.9) is — S03.7's `season_definition` + `license_tag` ids are constructed per-row inside build loops via pure id-constructor functions (`_season_definition_id`, `_license_tag_id`, plus the two bear-pathway equivalents). The two-primitive helper API reflects this split. `db.upsert_jurisdiction_binding` remains carve-out (schema-level UPDATE-clause identity exclusion from S03.6.1 OQ-S6.1-4 is strictly stronger than the application-level assert; documented in ADR-020 § Context). Test suite delta: +37 tests (1128 → **1165 + 2 skipped**). Quality gates at merge: ruff + mypy per-file + pytest + `cubic review --json` all clean.

### Context

Three `id text`-PK UPSERT helpers in `ingestion/ingestion/lib/db.py` currently update slug-encoded fields under the same `id` on conflict:

| Helper | DDL line | Slug-encoded fields updated on conflict |
|---|---|---|
| `_UPSERT_SEASON_DEFINITION_SQL` ([`db.py:110`](../ingestion/ingestion/lib/db.py#L110), S03.7) | season_definition | `name`, `weapon_type`, `residency` |
| `_UPSERT_LICENSE_TAG_SQL` ([`db.py:132`](../ingestion/ingestion/lib/db.py#L132), S03.7) | license_tag | `license_code`, `name`, `kind`, `species` |
| `_UPSERT_REPORTING_OBLIGATION_SQL` ([`db.py:194`](../ingestion/ingestion/lib/db.py#L194), S03.9) | reporting_obligation | `kind`, `deadline`, `applies_to_regions` |

For all three tables, the `id` slug is hand-encoded as a deterministic string built from a subset of the entity's structured fields (e.g., `reporting_obligation.id = "mt-bear-harvest-report-48hr-statewide"` encodes kind, deadline, and scope). If a future spec edit changes one of those structured fields without correspondingly updating the slug, the same `id` would silently carry different semantics under DO UPDATE — and any link-table rows (`license_season`, `regulation_season`, `regulation_license`, `regulation_reporting`) already pointing at that `id` would now reference an entity whose meaning has shifted.

### The risk

Drift between slug-derivation logic and the structured fields under the same `id` silently rewrites the meaning of existing rows that already have link-table references pointing at them. The UPSERT is the load-bearing point: it has no way to know that "the slug came from these fields, but the fields have changed since the slug was minted." Both states satisfy the conflict clause; the DO UPDATE wins by definition.

### Why it's V1-safe right now

- All three dispatch dicts (`_REPORTING_ROW_SPEC` in `load_reporting_obligations.py`; the corresponding spec constructions in `load_seasons_and_licenses.py`) are closed compile-time constants — there is no operator-runtime mutation path.
- Unit tests lock canonical slug↔field pairings (e.g., `test_statewide_harvest_report_fields`, `test_r1_tooth_submission_fields`, `test_r2to7_hide_skull_fields` for S03.9; similar assertions in S03.7 tests).
- V1 ingestion runs once against fresh artifacts; the first conflict in production would not occur until a year-over-year re-ingestion against a mutated dispatch dict.
- S03.9 ships a **local drift-guard at module load** (`load_reporting_obligations.py:_assert_dispatch_dict_drift_free`) as belt-and-suspenders — the assertion calls `_derive_expected_id_suffix(kind, deadline_hours, region_scope)` and raises `RuntimeError` if any spec entry's `id_suffix` doesn't match the derivation. This is S03.9-only by design — Q19 tracks the project-wide fix; do not propagate this pattern to new helpers without addressing Q19.

### Trigger for resolution

**The first year-over-year re-ingestion run.** This is when source documents change (e.g., MT FWP 2027 booklet) and adapters re-execute against an existing populated DB. Before then, the UPSERT's DO UPDATE clause never fires for slug-encoded fields. The architectural fix MUST land across all three helpers in a single PR before M2 ingestion runs begin.

### Leading option

**Option A — derive-and-assert (recommended).** Define `id_suffix` (or the full `id`) as a deterministic function of the slug-encoded structured fields, and assert at module load that every dispatch dict entry's `id` matches the derivation. Drift becomes impossible by construction. This is the right invariant for compile-time dispatch dicts. ADR will be needed at resolution to formalize the convention across `season_definition` / `license_tag` / `reporting_obligation`.

### Alternatives considered

- **Option B — no-update slug fields:** Remove slug-encoded fields from the UPDATE clause; allow only "refinement" fields (verbatim_rule, source, submission_url, etc.) to update on conflict. Effect: a spec edit that changes slug-encoded fields would mint a new `id` via INSERT, leaving the old row + its link-table references orphaned. Trades semantic-drift risk for orphan-link risk; not a clean improvement.
- **Option C — drop UPSERT:** Require operators to TRUNCATE the affected tables before re-runs. Trades idempotency for safety. Acceptable for V1 ergonomics but loses the "re-run without disruption" property that S03.6/S03.7/S03.8 explicitly cultivated.

### What moves this to a decision

- M2 planning lands and the project-wide ingestion-pattern PR is scoped (covers all three helpers in one commit).
- ADR drafted formalizing the slug-derivation convention.
- The local drift-guard in `load_reporting_obligations.py` is generalized into a shared helper and applied to the S03.7 dispatch dicts.

**Affected V1 entries:** 3 dispatch entries in `_REPORTING_ROW_SPEC` (S03.9); the S03.7 dispatch surface is broader (978 `season_definition` + 1225 `license_tag` rows derived from compile-time slug encodings — see S03.7 closure note for the breakdown).

**Working note:** S03.9.md (deleted at m1 tag per ADR-017 §6); Q19 / drift-guard decision narrative survives only via this open-question entry. The local module-load drift guard remains in `load_reporting_obligations.py::_assert_dispatch_dict_drift_free` as belt-and-suspenders until the project-wide fix lands.

---

## Q21: Should the geometry loaders pin-enforce the committed PAD-US manifest at fetch time (mirroring the PDF loaders' `expected_sha256` two-gates model)?

**Status (2026-06-24 via PRD 003 / M3 planning): RESOLVED — option (a), pin-enforce at fetch time; implemented in M3 epic E07.** The re-evaluation trigger ("M3 planning starts") fired; production intent (the user confirmed prod is coming post-OnX) makes dev/prod PAD-US snapshot parity a real correctness concern, satisfying option (a)'s "if dev/prod parity matters → ship (a)" criterion. The geometry loaders adopt the two-gates `expected_sha256`/`expected_layer_hash` model (mirroring the PDF loaders) in E07. No separate ADR — this is an established pattern (the PDF two-gates precedent), recorded in the E07 closure. The estimated-effort and option detail below stand as the implementation reference for E07.
**Surfaced by:** M2-build operator pass 2026-06-23 (two PAD-US 4.1 republish drifts in 18 calendar days: 2026-06-04 base → 2026-06-21 OID drift fixed by S06.6.1 → 2026-06-22 GeometryCollection drift fixed by S06.6.2)
**Touches:** `ingestion/ingestion/lib/arcgis.py` (`fetch_features` + `_require_objectid`), `ingestion/states/colorado/load_restricted_areas.py` (PAD-US Group B manifest+metadata fixture), `ingestion/states/colorado/load_gmus.py` (CPW FeatureServer; same pattern would extend), state-adapter fixture-commit convention (manifest+metadata committed; features-*.geojson gitignored)

### Context

PAD-US 4.1 (USGS Federal Fee Managers Authoritative FeatureServer) is the canonical source for the 10 V1 CO federal no-hunt zones. During the M2-build operator pass it republished **twice in 18 calendar days**, each republish breaking previously-merged + audited loader code:

- **2026-06-21**: top-level GeoJSON `id` field stopped being emitted unless `OBJECTID` is in the request's `outFields`. Fixed via S06.6.1 (PR #72) — added `"OBJECTID"` to `_RA_OUT_FIELDS` + introduced strict `_require_objectid` helper in `lib/arcgis.py`. Forensic signal: CRS shifted `4269 → 3857`, captured by `lib/arcgis._check_and_fix_projection`.
- **2026-06-22**: RMNP's republished geometry carries a ring self-intersection that `make_valid()` repairs into a `GeometryCollection`, losing 0.0676% polygonal area. Fixed via S06.6.2 (PR #73) — relaxed `geojson_to_multipolygon_wkt` area-preservation epsilon `rel_tol=1e-6 → 1e-3` with documented rationale.

The lib's fail-loud discipline + the mid-pass-carve-out pattern is **the project's current working solution** for upstream drift. The two carve-outs shipped clean and the operator pass completed.

### Why this is open vs decided

Dev-only-ever, mid-pass-carve-out is acceptable (slow but works). The next operator pass against the same dev env can re-use the S06.6.2 `000955Z` fixture as the pinned snapshot — no further drift bites unless we re-fetch from live.

Once prod env stands up, dev and prod could ingest **different PAD-US snapshots** if fetched on different days mid-republish — that's a real production correctness bug, not theoretical. The current architecture has the *detection* infrastructure (committed manifest = drift-detection reference) but lacks the *enforcement* policy (loader doesn't refuse to write when live SHA ≠ committed SHA).

### Options

- **(a) Pin-enforce at fetch time (mirrors PDF loaders' two-gates model).** Extend the geometry loaders' fetch path to take an `expected_sha256` (or equivalent layer_hash) param; refuse to write if live re-fetch SHA differs from committed manifest; require a tracked PR with re-pinned manifest to consume a new upstream snapshot. ~1 week of implementation. Mirrors S06.1's `pdf_fetch.fetch_pdf` `expected_sha256` param model. **Recommended IF prod env is coming.**
- **(b) Continue with the mid-pass-carve-out pattern.** Zero code; unbounded ongoing time cost per republish. Only acceptable for dev-only-ever.
- **(c) Re-source from a "more stable" layer.** **No clean alternative exists** — PAD-US 4.1 is the canonical federal-lands aggregator; NPS Boundary Service is partial (no AFA, no USFWS); USFWS Cadastral wrong domain (no NPS/NMs); per-park endpoints are ~9 separate sources to track. Tradeoffs without a clear winner.

### What moves this to a decision

**Trigger condition for re-evaluation:** prod env setup begins (the user confirmed 2026-06-23 that prod is coming post-E06 close), OR M3 planning starts via `/plan-next-milestone`, whichever is first. At that evaluation point:

- If we've hit a 3rd drift in the meantime → ship (a)
- If dev/prod parity matters (multi-environment ingest) → ship (a)
- Otherwise → defer to M3 with documented rationale

Decision owner: human (user) + PM jointly at the trigger event.

### Estimated effort if (a) commits

~1 week implementation: extend `lib/arcgis.fetch_features` (and any sibling geometry fetch helpers) to take an `expected_layer_hash` / `expected_sha256` param mirroring `pdf_fetch.fetch_pdf`'s shape; thread the committed manifest's `layer_hash` through the loader call sites (`load_restricted_areas.py`, `load_gmus.py`, others as discovered); add a drift-marker workflow ("operator deletes marker after acknowledging the drift; until then, downstream re-fetches refuse to proceed") mirroring the existing `*-pending-reextraction.flag` PDF pattern; new unit tests for the gate + the drift-marker recovery path; new pitfall under `.roughly/known-pitfalls.md` § "Integration — ArcGIS" formalizing the two-gates model for geometry fetches.

### Cross-references

- S06.6.1 closure: `docs/planning/epics/E06-colorado-regulation-text-ingestion.md` § "S06.6.1: PAD-US OBJECTID outFields hardening"
- S06.6.2 closure: `docs/planning/epics/E06-colorado-regulation-text-ingestion.md` § "S06.6.2: PAD-US GeometryCollection area-preservation handling"
- M2-build operator pass closure narrative: `docs/planning/README.md` "Last Updated" entry 2026-06-23
- Working analog (PDF side): S06.1's `pdf_fetch.fetch_pdf` `expected_sha256` param (the project precedent for the two-gates model)

---

## Q22: What is the production auth model for the MCP server?

**Status:** Open (deferred; trigger = production go-decision / post-OnX + a go-to-market strategy)
**Surfaced by:** M3 planning 2026-06-24 ([PRD 003](planning/prds/003-M3-canonical-interface.md))
**Touches:** the MCP server auth seam ([ADR-023](adrs/ADR-023-remote-mcp-server-posture.md)), `@cloudflare/workers-oauth-provider`, deployment

### Context

M3 ships an **OAuth-2.1-ready but unenforced** auth posture: a **single open, read-only MCP endpoint** (public data; no enforced authentication, consistent with the standing "no authentication in V1" scope), with the OAuth-2.1 auth seam **wired as one middleware integration point but unenforced** — the drop-in for real auth later. A static token is deliberately *not* relied on as a V1 boundary: on a single open endpoint a token can't be enforced (a client could omit it and take the open path), and a browser-shipped token is exposed in client-side code anyway. Baseline abuse protection in V1 is Cloudflare's **ambient DDoS/WAF**. Any *enforced* token, tier, quota, or authentication requires a real boundary — a separate authenticated route or Cloudflare Access — and is determined by go-to-market strategy, explicitly out of M3 scope.

### What needs to be decided (at the trigger)

- IdP / OAuth provider choice (Cloudflare Access vs. a third-party IdP via `@cloudflare/workers-oauth-provider`: GitHub / Google / Auth0 / WorkOS / Stytch).
- Scope design and whether any per-consumer authorization beyond metering is warranted.
- API-key tiering / B2B access (B2B API access is a V1 non-goal per `context.md`; revisit if GTM calls for it).
- Rate-limit / quota policy (V1 has only Cloudflare's ambient DDoS/WAF; *configured* rate-limiting + the policy itself are GTM-adjacent V2 work, and an enforced quota needs a real boundary per above).
- Monetization / metering model, if any.

### What moves this to a decision

A production go-decision (e.g., the outcome of the OnX process) plus a GTM strategy. No V1 action; M3's minimal seam is sufficient until then.

**Resolution home:** an ADR (extending or superseding ADR-023's auth-seam section) once the GTM model is known.

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
