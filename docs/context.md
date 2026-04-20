# Context

This document is the shared frame for everyone working on HuntReady — human or agent. It answers the questions that downstream work (architecture, ADRs, epics, implementation) is expected to be consistent with. If a decision in this document is wrong, fix it here first, then propagate.

Nothing in this document is a schedule. Nothing here is a feature list. This is the *frame*.

## What HuntReady is

HuntReady is a regulatory companion for licensed hunting activity in the United States. It answers the question:

> *"I'm planning to hunt [species] at [coordinate] on [date]. What do I need to know, what do I need to buy, and who do I need to tell?"*

For that query it returns: applicable regulation sections with source citations, license and tag requirements with direct links to the state agency purchase flows, season windows and methods of take, reporting obligations (pre-hunt and post-hunt), and agency contacts for the relevant district.

## What HuntReady is not

Named explicitly so that scope decisions downstream have a sharp reference.

- Not a legal service. HuntReady does not interpret regulations or opine on what is legal. It routes to authoritative sources.
- Not a mapping product. The map surface exists because hunters need a spatial entry point; the map is not the differentiator.
- Not a license marketplace. License purchases happen on state agency sites. HuntReady delivers the hunter to the right flow with the right context; it does not proxy the transaction.
- Not a harvest tracker, a social network, an outfitter directory, or a hunt-planning community. Those are real products. They are different products.
- Not a super-app. The failure mode of outdoor-rec products is ambition inflation. HuntReady succeeds by doing the document layer well and nothing else.

## The user

Primary user: a licensed or soon-to-be-licensed hunter planning a trip that involves any combination of: a species or unit they haven't hunted before, a state whose regulations they don't have memorized, a draw-based tag with an application deadline, or a shift in plans (weather, access, cancellation) that requires validating new ground on short notice.

This user is technically comfortable — smartphone-native, already paying for at least one outdoor-recreation app, willing to read regulations if they can be routed to the relevant section. They are not a novice to hunting; HuntReady is not a hunter education product. They are a novice to *this specific hunt*, and that is where regulation compliance breaks down.

Secondary users (design for, don't optimize for in V1):

- Guide services and outfitters, who need regulation verification across multiple clients and jurisdictions.
- Developers building outdoor-recreation products who want regulation data as a service.

We do not design for: state agency staff, law enforcement, researchers, policymakers. These are legitimate audiences for regulation data but not for this product.

## Authority boundaries

HuntReady preserves the authority of state wildlife agencies. This is a product discipline and a liability discipline. It is enforced in three places:

1. **At the schema level.** Every regulation record requires a source citation — URL, agency, publication date. Records without citations fail validation and do not enter the corpus.
2. **At the response level.** Every MCP tool response and every UI surface that renders regulation content includes the source link and publication date. Users can always reach the authoritative source in one click.
3. **At the text level.** Regulation text is carried *verbatim* from the source. The product does not paraphrase, simplify, or rewrite regulations. Ingestion may extract and structure; it does not summarize.

Corollary: if a regulation cannot be rendered faithfully at the text level, it is not rendered at all. A partial or paraphrased regulation is worse than a missing one, because it creates the appearance of authority the product does not have.

## The shape of the product

HuntReady is a data platform with three V1 consumer surfaces. The platform is the product; the surfaces are ways to reach it.

- **MCP server.** The canonical interface. Agentic clients (Claude Desktop, Claude Code, Cursor, Windsurf) call tools and receive structured regulation data. This is the interface the rest of the platform is organized around.
- **Web companion.** A thin, map-first consumer surface. Drop a pin, pick species and date, receive the full regulatory stack for that query. Calls the MCP server through a minimal HTTP adapter.
- **Claude Code plugin.** A developer-facing surface that makes HuntReady's agentic nature legible at the development layer, not just the product layer. Ships two skills: `regulation-lookup` for querying during development, and `ingest-state` for onboarding new state data.

A native mobile app, a B2B API with packaging, authentication, billing, and a hunter account system are all post-V1. They are not architectural gaps; they are scope choices.

## Why this is a platform, not a feature

Stated explicitly because it is loadbearing for every architectural decision downstream.

One regulation corpus serves all three V1 surfaces — and serves every future surface we haven't built yet — from a single schema. The ingestion work (turning messy state-agency outputs into clean structured records) is the expensive work. The surfaces are cheap by comparison. Building any one surface without the shared platform would capture a small fraction of the value of the work.

The architectural commitments that follow from this are: ingestion upstream and offline; MCP as the canonical interface; schema versioned from day one; authority preserved, not replaced; and Postgres+PostGIS as the storage layer from V1 onward. Each is captured as a separate ADR.

## What "done" looks like at V1

V1 is done when the following are all true:

- Two states are ingested, schema-conformant, and queryable: Montana and Colorado.
- Five species are supported in each state: elk, mule deer, whitetail, pronghorn, black bear.
- The MCP server exposes five tools: `get_regulations`, `check_land_status`, `list_seasons`, `get_tag_requirements`, `get_agency_contacts`.
- The web companion runs at a public URL and supports the primary flow end-to-end (pin drop → species/date → regulations with sources).
- The Claude Code plugin installs cleanly and ships two working skills.
- The repository contains, at minimum: `context.md`, `architecture.md`, `roadmap.md`, `open-questions.md`, a populated `adrs/` directory, and a README that gets a cold visitor to a working local install in under ten minutes.
- A cold visitor can form an accurate impression of the product, the architecture, and the development process in under fifteen minutes of reading.

The last two conditions are not cosmetic. The repository is part of the product at V1.

## What comes after V1

V1 is a complete, honest, narrow demonstration. V2 is the direction, not a commitment:

- Expand state coverage (Idaho, Wyoming, Utah, Washington as likely next candidates).
- Expand species coverage within existing states, especially small game and waterfowl.
- Add automated ingestion scheduling with drift detection against source documents.
- Add a B2B API surface with authentication, rate limiting, and tiered access.
- Add a hunter account system to power trip planning, tag application reminders, and favorited units.

V2 is explicitly out of scope for the V1 build. Decisions made during V1 should keep V2 reachable without committing to it.

## Operating principles

Three principles that resolve downstream ambiguity when it arises:

**Depth before breadth.** Two states ingested well beats five states ingested badly. Five species modeled correctly beats twenty species modeled loosely. The schema is the product; shallow coverage undermines the schema.

**The schema is the contract.** When a state's regulations don't fit the schema cleanly, the default action is to improve the schema, not to special-case the state. The schema's job is to accommodate the full range of U.S. hunting regulation without losing its shape. Colorado, in particular, is chosen as a seed state because its draw system stress-tests the schema early.

**Every surface is a client.** The MCP server is the canonical interface. The web companion is a client of it. The Claude Code plugin is a client of it. Future B2B API consumers are clients of it. Any work that bypasses this — a web feature that talks directly to the data files, a plugin skill that reimplements a tool — is a correctness risk and a maintenance burden. Resist it.

## Non-technical context for collaborators

HuntReady is being built by a single developer with significant AI-assisted pairing, over a compressed timeline, as a portfolio and product artifact. This context matters for two reasons:

First, scope discipline is unusually important. There is no team to absorb overreach. Every commitment has to be honored by one person.

Second, agentic development is a first-class feature of the project, not an incidental delivery mechanism. The Claude Code plugin exists because the development process itself is part of what HuntReady demonstrates. When in doubt about whether to document a decision, an assumption, or a piece of context — document it. The documentation is the handoff mechanism to every future session with an agent, and every future collaborator.
