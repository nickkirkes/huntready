# Roadmap

This document describes HuntReady's trajectory in outcome-based milestones. Milestones name the observable state of the world when they are complete, not the activities that produce them. A milestone is either reached or it is not; partial completion is not a status.

This document does not contain dates. Dates belong in sprint planning, not in roadmap. The expected cadence is "V1 complete in roughly 10–14 focused working days," and if that stretches it stretches; the milestone structure is the durable artifact.

## Milestone structure

Milestones are numbered M0–M5. Each names its outcome, the observable signals that the milestone is complete, and the minimum set of deliverables that produce those signals. Deliverables are not a task list; they are the *visible surface* of the work.

Dependencies run strictly forward. M1 cannot begin until M0 is complete. M3 can begin in parallel with M2 only where noted. M5 is the final milestone; anything beyond it is V2 and out of scope.

---

## M0 — Frame locked

**Outcome:** The product, its boundaries, and its architecture are decided and written down. Anyone (human or agent) can read the repo and know what is being built, what is deliberately not being built, and why.

**Signals:**
- `context.md`, `architecture.md`, `roadmap.md`, and `open-questions.md` exist in the repo and are internally consistent.
- The initial ADR set is drafted and committed (the loadbearing decisions: MCP-as-canonical-interface, ingestion-upstream-and-offline, authority-preservation, Python+TS split, schema-versioned, seed-states, Postgres+PostGIS-as-storage, verbatim-regulation-text).
- A reader who sees the repo for the first time can form an accurate mental model of the product in under fifteen minutes.

**Deliverables:**
- The four root documents above.
- `adrs/` directory with the initial ADR set.
- Repository skeleton with top-level directories (`ingestion/`, `mcp-server/`, `web/`, `plugin/`, `supabase/`) and placeholder READMEs.
- Supabase project provisioned, PostGIS extension enabled, initial migration in place defining the `regulations`, `units`, and `sources` tables. RLS policies deny public PostgREST access; only the service-role key can read or write.

**Exit criteria:** documents read as consistent. Open questions that are genuinely blocking are resolved or escalated. Nothing in the thinking layer is still load-bearing for the build layer. The database is reachable and ready to accept data.

---

## M1 — Schema proven on one state

**Outcome:** Montana's regulation data is ingested, normalized, schema-conformant, and queryable from Postgres. The ingestion pattern works end-to-end for a single state, and the schema has survived first contact with real data.

**Signals:**
- Montana regulations and unit boundaries are present in Supabase Postgres, validated against the schema, and contain records for the five V1 species.
- The ingestion pipeline for Montana is reproducible — a collaborator can clone the repo, run `make ingest STATE=montana` with the appropriate Supabase credentials, and produce the same loaded state.
- Spatial queries against Montana unit boundaries work via PostGIS (`ST_Contains`, `ST_Intersects`).
- The schema has been revised at least once in response to real Montana data. (If it hasn't, the schema is probably wrong and not being stress-tested.)
- An ADR documents any schema changes made during this milestone, and migrations reflect them.

**Deliverables:**
- `ingestion/states/montana/` complete (fetch, extract, normalize, validate, load, sources.yaml).
- `ingestion/lib/` primitives for PDF extraction, schema validation, PostGIS-aware geometry preparation, and the Postgres writer.
- Montana records loaded into Supabase.
- Migrations in `supabase/migrations/` reflecting any schema evolution during M1.

**Exit criteria:** a second developer could, in theory, onboard Idaho using the Montana adapter as a reference, without further schema changes. "In theory" is the honest standard here; the real test comes in M2.

---

## M2 — Schema survives a second, harder state

**Outcome:** Colorado is ingested using the same pattern, and the schema holds. Where it doesn't hold, it has been extended (not special-cased) to accommodate Colorado's draw-based tag system. Multi-state is now a real property of the product, not a claim.

**Signals:**
- Colorado regulations and unit boundaries are present in Supabase Postgres and validate.
- Colorado's draw-based tag mechanics are modeled in the schema in a way that generalizes beyond Colorado — any state with a preference-point or points-weighted draw system can use the same fields.
- No Colorado-specific code paths exist in the shared ingestion library. State-specific logic lives in `ingestion/states/colorado/`.
- If the schema changed materially in M2, an ADR documents why and migrations reflect it.

**Deliverables:**
- `ingestion/states/colorado/` complete.
- Colorado records loaded into Supabase.
- Schema extensions (if any) reflected in the TypeScript types, the Python schema definitions, and Postgres migrations.

**Exit criteria:** the multi-state claim is defensible. A reviewer opening the repo sees two states' worth of real data and one schema.

*M2 may begin in parallel with M3 once Montana ingestion is stable, if capacity allows. It is not a dependency of M3.*

---

## M3 — Canonical interface live

**Outcome:** The MCP server is the canonical interface to HuntReady's data, exposing the V1 tool set, backed by the Montana corpus. It is installable locally by any MCP-capable agentic client.

**Signals:**
- The MCP server runs locally and registers cleanly with Claude Desktop.
- All five V1 tools (`get_regulations`, `check_land_status`, `list_seasons`, `get_tag_requirements`, `get_agency_contacts`) return properly structured, source-cited responses for Montana queries.
- A query to `get_regulations` for an out-of-scope species or state returns a structured "not covered" response, not a silent empty result.
- Every tool response includes a `sources` array.
- The HTTP shim that exposes the tools for the web companion is live and documented.

**Deliverables:**
- `mcp-server/` with the V1 tools implemented.
- `mcp-server/http.ts` exposing REST-style endpoints.
- `mcp-server/README.md` documenting each tool's shape and a worked example.
- A working `.mcp-config.json` at the repo root.
- Tests for each tool: at minimum one happy path, one missing-data path.

**Exit criteria:** an agentic client can hold a useful, grounded conversation with HuntReady about hunting in Montana. Colorado support follows automatically once M2 lands.

---

## M4 — Consumer surface live

**Outcome:** The web companion is deployed, publicly reachable, and supports the full primary flow end-to-end. A hunter can land on the page, drop a pin, pick species and date, and receive a complete regulation response with sources.

**Signals:**
- The web app is deployed to a public URL (Vercel or equivalent).
- The MCP server's HTTP shim is deployed to a public URL (Fly.io, Railway, or equivalent).
- The primary flow works for Montana and Colorado, for all five V1 species.
- Source citations are prominently displayed on every regulation panel.
- A reviewer can reach the demo in one click and understand the product in under two minutes.

**Deliverables:**
- `web/` complete: map view, species/date picker, regulation panel with source links, tag info panel, agency contacts.
- Deployment configuration for both the web app and the MCP server HTTP shim.
- A single Mapbox token configured via environment variable; no other secrets.

**Exit criteria:** the product is usable by a hunter who has never heard of HuntReady before, with no onboarding beyond the landing page.

---

## M5 — Agentic development pattern shipped

**Outcome:** The Claude Code plugin is installable, functional, and documented. The plugin's existence in the repo makes a credible claim about how HuntReady is developed, and that claim is supported by observable evidence.

**Signals:**
- `plugin/` directory contains a `.claude-plugin/` manifest and a `plugins/huntready/` structure mirroring the conventional Claude Code plugin pattern.
- The `regulation-lookup` skill is installable, triggers on the expected queries, and returns correct data for Montana and Colorado.
- The `ingest-state` skill is installable, and a developer following its walkthrough can produce a scaffolded new state adapter directory with the correct structure.
- The repository README promotes the plugin as a first-class surface of the product, not an afterthought.
- An optional: a recorded demonstration of using the `ingest-state` skill to onboard a third state (Wyoming or Idaho) end-to-end. This is a stretch deliverable — attempted only if M1–M4 are solid.

**Deliverables:**
- `plugin/` directory with two skills.
- Skill-level `SKILL.md` files with properly crafted trigger descriptions.
- Installation documentation in the plugin README.
- Optional: a short demonstration video of the onboarding flow.

**Exit criteria:** HuntReady demonstrates not just what it does, but how it was built — and the "how" is agentic-native from the development layer up.

---

## V1 complete

V1 is complete when M0–M5 are all reached. The repository at that point is a portfolio-grade artifact and a working product demonstration. The exact wall-clock time to completion is secondary to the integrity of each milestone.

## What is out of scope for V1

Repeating from `context.md` for clarity, because roadmap readers will ask:

- Native mobile applications.
- User accounts, authentication, saved queries.
- Automated ingestion scheduling or drift detection.
- Rate-limited, authenticated, or billed B2B API access.
- Harvest tracking, hunter education verification, or license purchase proxying.
- Any state beyond Montana and Colorado, with the optional Wyoming/Idaho stretch noted in M5.

These are not gaps. They are deliberate scope decisions. If a milestone starts pulling toward any of them, the milestone is wrong or the scope is wrong; resolve in that order.

## Parallelization and dependencies

The dependency graph is mostly linear, with one exception:

```
M0 ──► M1 ──► M2 ──► M4
          └──► M3 ──► M4
                      └──► M5
```

M1 unblocks both M2 (more state data) and M3 (MCP server against Montana). Those can proceed in parallel if capacity allows. M4 depends on M3 being functional; it does not strictly depend on M2, though launching M4 without M2 would leave Colorado out of the public demo and is not recommended. M5 depends on M4 being deployed and on the MCP server being stable.

## What the roadmap is *for*

Two audiences.

For the builder: a way to know what "finished" means at each stage, so that completion is a clear decision and not a vibe. Milestones are checkpoints to stop, evaluate, and decide whether to proceed, adjust, or cut.

For PM agents drafting epics and stories: a structured backbone to decompose into work. Each milestone is one epic (or a small set of related epics); each deliverable is a potential story or story cluster. The roadmap is intentionally written at a level of abstraction that an agent can use without needing to ask what "ingested" or "deployed" mean in context — the context doc and architecture doc supply the rest.
