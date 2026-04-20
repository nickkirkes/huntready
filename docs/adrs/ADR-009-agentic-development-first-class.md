# ADR-009: Agentic Development as a First-Class Project Feature

**Date:** 2026-04
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** agentic-dev, process

---

## Context

HuntReady is being built by a single developer with significant AI-assisted pairing, over a compressed ten-to-fourteen-day V1 timeline, as both a portfolio and a product artifact. The development process is not incidental to what the repository communicates; it is evidence that the product is well-thought-out. Regulation ingestion is the kind of work where a developer in 2026 should be pairing with an agent — the inputs are messy PDFs and ArcGIS endpoints and the outputs are schema-shaped. Hiding the pairing from the repository would misrepresent the work.

## Decision

HuntReady treats agentic development as a first-class project feature: the repository ships a Claude Code plugin with developer-facing skills, and documentation is written as the primary handoff mechanism between sessions.

## Reasoning

Two commitments flow from the decision. The first is the Claude Code plugin in `plugin/`, shipping two skills. `regulation-lookup` wraps HuntReady's MCP tools for use during development so an engineer can verify an adapter's output from inside a session. `ingest-state` walks a developer through fetching sources, running the extractor, normalizing against the schema, and scaffolding a new adapter directory — encoding the onboarding path learned during Montana and Colorado into a repeatable workflow. The plugin uses the conventional `.claude-plugin/` + `plugins/<name>/skills/<skill>/SKILL.md` structure.

The second commitment is documentation as the handoff mechanism. `context.md`, `architecture.md`, `roadmap.md`, `open-questions.md`, and the ADRs exist so that any session — human or agent — can pick up where the last left off without rederiving decisions. Open questions flow into ADRs; ADRs flow into architecture updates; architecture updates flow into code. The documentation is the connective tissue that lets agentic development scale past any single session's context window.

This ADR is meta with respect to [ADR-002](ADR-002-mcp-canonical-interface.md): the plugin is a client of the canonical server, not a parallel implementation.

## Alternatives Considered

**No plugin; rely on Claude Code's default MCP integration.** Rejected because the plugin's skills encode development-time workflows the default integration does not supply. Without them, the workflows exist as tribal knowledge in a README.

**Plugin shipped separately, outside the main repository.** Rejected because the repository is part of the product at V1; removing the plugin from it would understate a real commitment about how the project is built.

**Skip the documentation layer and rely on code clarity.** Rejected because the cost of a future session rediscovering reasoning is higher than writing it down as decisions are made.

## Consequences

### Positive

- The repository itself is evidence of how the project was built; the "how" is not a separate pitch.
- Future agentic sessions have a coherent handoff surface, reducing rederivation cost per conversation.
- The `ingest-state` skill is a direct investment in V2 state-expansion velocity.

### Negative

- The plugin is additional V1 scope. Time spent on it is time not spent on ingestion or serving polish; if M5 runs long the plugin is the piece most at risk of being thin.
- Writing documentation as a primary deliverable imposes a real ongoing tax — roughly doubling the cognitive cost of a commit that involves an architectural choice.
- The plugin surface is unfamiliar to reviewers who do not use Claude Code and can read as noise rather than signal to that audience.

### Neutral

- This ADR makes agentic development part of HuntReady's identity. Any future decision about whether the project is "still agentic-native" has this ADR as its baseline.

## Links

- [ADR-002](ADR-002-mcp-canonical-interface.md) — The plugin is a client of the canonical interface, not a parallel path.
- [`docs/context.md`](../context.md) — "Non-technical context for collaborators."
- [`docs/roadmap.md`](../roadmap.md) — Milestone M5 is the delivery of this ADR.
