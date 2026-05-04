# Architecture Decision Records

This directory contains the architecture decision records (ADRs) for HuntReady. ADRs capture loadbearing technical decisions at the point they are made, with enough reasoning that a future reader — human or agent — can understand not just *what* was decided but *why*.

## What belongs in an ADR

An ADR captures a decision that meets at least one of:

- Shapes how the code is organized or written (e.g., language split, canonical interface).
- Commits to a specific technology or vendor (e.g., Supabase, PostGIS).
- Closes off a class of future options (e.g., "no PostgREST as a consumer surface").
- Would be asked "why did you do it this way?" by a reviewer six months from now.

Decisions that don't meet these bars — configuration details, minor file layout, readily reversible choices — live in the relevant code, the README, or commit messages. Not every choice is an ADR.

## Numbering

ADRs are numbered sequentially, zero-padded to three digits, and named with a short kebab-case title:

```
ADR-001-authority-preserved.md
ADR-002-mcp-canonical-interface.md
ADR-003-ingestion-upstream-offline.md
```

Numbers are stable IDs. Once an ADR is assigned a number, that number is not reused even if the ADR is later superseded or deprecated. References to ADRs elsewhere in the repo use the bare number (`ADR-004`) rather than the full title.

## Status

Every ADR has one of the following statuses:

- **Proposed** — the decision is drafted but not yet committed to. Used when writing an ADR *before* implementation begins, as a decision-review artifact.
- **Accepted** — the decision is in force. This is the default active status.
- **Deprecated** — the decision was once in force but is no longer relevant. The ADR is kept for historical context but does not describe current practice.
- **Superseded by ADR-00X** — the decision has been replaced by a later ADR. The superseding ADR explains the change.

ADRs are not deleted. Deprecated and superseded ADRs stay in place so that the decision history is navigable.

## Tag vocabulary

Tags are drawn from the following controlled list. New tags can be added here, but an ADR should not invent a tag that doesn't exist in this document.

- **storage** — decisions about the data layer (database, migrations, schemas as stored).
- **mcp** — decisions about the MCP server and its tools.
- **ingestion** — decisions about the Python ingestion pipeline.
- **web** — decisions about the Next.js web companion.
- **plugin** — decisions about the Claude Code plugin.
- **schema** — decisions about the regulation data schema itself.
- **scope** — decisions about what is and is not in V1.
- **agentic-dev** — decisions about how the project uses AI-assisted development.
- **product** — decisions about the product's shape, boundaries, and user-facing commitments.
- **deployment** — decisions about hosting, deploy targets, environments.
- **process** — decisions about how work is done (commit conventions, review practices).

Most ADRs carry one or two tags. If an ADR needs three or more, it may be doing too much and should be split.

## Index

<!-- Keep this table updated as ADRs are added. Sort by number. -->

| #   | Title                                              | Status    | Tags                |
| --- | -------------------------------------------------- | --------- | ------------------- |
| 001 | Authority Preserved, Not Replaced                  | Accepted  | product             |
| 002 | MCP Server as Canonical Interface                  | Accepted  | mcp, scope          |
| 003 | Ingestion Upstream and Offline                     | Accepted  | ingestion, scope    |
| 004 | Supabase Postgres + PostGIS as the Storage Layer   | Accepted  | storage             |
| 005 | Python for Ingestion, TypeScript for Serving       | Accepted  | ingestion, mcp, web |
| 006 | Schema Versioned From Day One                      | Accepted  | schema              |
| 007 | Montana and Colorado as Seed States                | Accepted  | scope, ingestion    |
| 008 | Verbatim Regulation Text                           | Accepted  | schema, product     |
| 009 | Agentic Development as a First-Class Project Feature | Accepted | agentic-dev, process |
| 010 | Decomposed Entity Model                            | Accepted  | schema, storage     |
| 011 | Shape C Response Envelope                          | Accepted  | mcp, schema         |
| 012 | Draw Mechanics as Sibling Entity                   | Accepted  | schema              |
| 013 | Server Returns Structure, Client Composes Presentation | Accepted | mcp, product        |
| 014 | SourceCitation `gis_layer` Document Type           | Accepted  | schema              |
| 015 | Geometry Verbatim Rule and REG+COMMENTS Handling   | Accepted  | schema              |
| 016 | Digitization-Tolerant Geometry Overlay Containment | Accepted  | ingestion, schema   |
| 017 | Confidence Calibration and Parent-Inheritance Rule | Accepted  | ingestion, schema   |
| 018 | E03 Schema Additions — license_season, geometry.legal_description, geometry.kind='state' | Accepted | schema, ingestion |

ADRs not yet drafted show `—` in the Status column. Once drafted and committed, Status becomes `Accepted` (or `Proposed` if written ahead of implementation).

## Template

New ADRs use the template in [`TEMPLATE.md`](TEMPLATE.md). It is short and opinionated; fill in every section, and prefer brevity over thoroughness.

## Writing conventions

A few conventions that keep the ADR set readable:

- **One decision per ADR.** If the ADR contains two decisions, split it. The exception is when two decisions are genuinely inseparable and splitting them would lose context.
- **Decision in one or two sentences.** If the decision takes a paragraph to state, it is probably two decisions or not yet decided.
- **Target length: 300-700 words.** Under 300 is usually too thin to carry honest reasoning; over 700 is usually doing more than one decision's worth of work. The extractive ADRs (those recording a decision already settled in upstream documents) tend to land 500-650; the argumentative ADRs (those where the reasoning is load-bearing and the cross-references are dense) tend to land 650-700.
- **Reasoning is prose, not bullets, unless the reasoning genuinely is a list.** Prose makes the thinking legible; bullets hide it behind formatting.
- **Consequences are honest about the negative.** If an ADR has no negative consequences listed, either the decision is trivial or the author wasn't thinking hard enough.
- **Alternatives are named and dismissed specifically.** "We considered option X and rejected it because of Y" is useful. "We considered other options" is not.
- **Links are kept current.** When an ADR references another ADR or a doc, the link should work. When files move, links get updated.

## How ADRs relate to other docs

- **`context.md`** establishes what HuntReady is. ADRs operate within that frame; an ADR cannot contradict context.md without updating it first.
- **`architecture.md`** describes the system as it exists. ADRs are the *reasoning* behind the architecture. If architecture.md and an Accepted ADR disagree, one of them is wrong and needs to be fixed.
- **`roadmap.md`** describes what we're building next. ADRs usually precede the roadmap work they enable; an M1 deliverable should be able to point at the ADRs that justify its shape.
- **`open-questions.md`** is the inbox. Questions get resolved into ADRs (or into smaller edits to context.md / architecture.md) and then removed from open-questions.md.

The flow is: question arises → captured in `open-questions.md` → resolved in an ADR → architecture/context updated to reflect the ADR → question removed from `open-questions.md`. This is the handoff mechanism that lets an agent pick up work mid-stream without needing to rederive decisions.
