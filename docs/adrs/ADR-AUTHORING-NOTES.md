# ADR Authoring Notes

Notes from the team that drafted ADRs 001–009. Records tensions, inferences, and items the team wants flagged before the Proposed → Accepted review pass.

## Source sufficiency — where reasoning is fully supported vs. inferred

All nine ADRs are drawn from load-bearing statements in `context.md`, `architecture.md`, `roadmap.md`, `open-questions.md`, and the six research documents. No ADR invents reasoning the source material does not support. A few ADRs lean more on one source than another; the team wants the reviewer to know which, so the Accepted pass can verify.

- **ADR-001, ADR-002, ADR-003, ADR-004, ADR-006, ADR-008** are restatements of the four "architectural commitments" in `architecture.md` plus the storage and authority sections. The reasoning sits directly on existing prose; the ADRs organize it and add consequences.
- **ADR-005** (Python/TypeScript split) is well-supported for the Python side (`architecture.md` "`ingestion/`" section, Montana source-structure research), and supported but less explicitly for the TypeScript side — the claim that Claude Code's plugin host is "TypeScript-native" is stated here by inference from the Anthropic MCP SDK's TypeScript reference implementation and from Next.js being TypeScript-native. If the plugin surface turns out to be neutral with respect to language, this ADR's third reason for TypeScript weakens but the first two still hold.
- **ADR-007** (Montana and Colorado as seed states) is the ADR with the strongest research evidence: four research documents directly support it. The negative consequence "each new state introduces its own source-evaluation work" is a projection — the V1 evidence cannot yet tell us how much variance to expect in V2. The team is comfortable with it as a negative consequence because it is a real unknown, not a fabricated one, but flagging it as projection.
- **ADR-009** (agentic development as first-class) is drawn from `context.md`'s "Non-technical context for collaborators" and roadmap M5. The specific claim that documentation "roughly doubles the cognitive cost" of an architectural commit is a qualitative estimate the team felt confident making given the one-developer, one-agent context, but it is not quantified in the source material.

## Consequences-section honesty — every ADR has a credible negative

The orchestrator's hard rule is "no ADR ships without an honest negative." The team checked each ADR and stands behind the Negatives as real. The two negatives the team debated:

- **ADR-006 (Schema Versioned):** the team initially drafted a weak negative ("additional complexity"). It was strengthened to name the concrete burden (dual representation: migration + version bump; supporting multiple concurrent versions during transitions; three-place schema duplication compounding the work). Current version is credible.
- **ADR-007 (Seed States):** the team debated whether "Wyoming/Idaho/Utah/Washington absent from V1" counts as a negative of this ADR or is just the trivial consequence of picking any two states. Kept it because a reviewer whose interest is outside Montana and Colorado has a real, product-level disappointment, not an abstract one.

No ADR needed to be held from shipping for lack of a credible negative.

## Tensions between ADRs

Two areas the team wants the review pass to read for consistency:

**Schema duplication (ADR-005 + ADR-006).** ADR-005 accepts manual three-place schema duplication (Postgres DDL, TypeScript, Python) as the cost of the language split. ADR-006 then treats schema versioning as a first-class commitment. Together, these compound: every schema version bump propagates to three files and their test suites. The ADRs acknowledge the compounded cost but do not resolve it — resolution is deferred to open question Q8 (schema unification) and is not a V1 ADR. The team thinks this is the right posture but wants it flagged so the reviewer notices the coupling.

**Offline ingestion + freshness (ADR-003).** ADR-003 commits to offline batch ingestion. The architecture doc's operational posture carries an `is_stale` flag at 180 days, which means a regulation change between ingestion runs is invisible up to that window. This is accepted in ADR-003's Negatives and is coherent with "V1 ingests at build time" in `architecture.md`. But for Montana, the 2026 Black Bear correction arrived one day after the base booklet — a sub-24-hour lag. The V1 operational cadence does not commit to sub-24-hour latency, which means the correction path is correct in principle (schema supports it; see ADR-006) but the timing guarantee is not strong. Not a contradiction; worth noting.

## Format and length

The orchestrator set a 250–500 word target per ADR. Final word counts (full-file, including frontmatter and Links):

| ADR | Words |
| --- | ----- |
| 001 | 545 |
| 002 | 580 |
| 003 | 595 |
| 004 | 587 |
| 005 | 600 |
| 006 | 597 |
| 007 | 621 |
| 008 | 627 |
| 009 | 616 |

All nine exceed the 500-word target by 45–130 words. The team did two trim passes and believes further cuts would start dropping load-bearing evidence (particularly ADR-007's dual-state justification and ADR-008's statutory-precision example). The team reads "over 500 is probably doing more than one decision's worth of work" as a heuristic rather than a hard ceiling; none of these ADRs is carrying two decisions, and the over-length is template scaffolding plus evidence, not padding. The team suggests the Accepted pass either (a) accept the 545–627 range as the practical floor for ADRs that cite research evidence, or (b) formally relax the target to 300–650 in the README.

If the target is to be held strictly, ADR-007 and ADR-008 are the two that most resist cutting, and the team would rather flag that here than trim further.

## Items the team wanted to include but could not fit

- **ADR-004** wanted a concrete example of why RLS-denying PostgREST matters in practice — e.g., a screenshot of what the Supabase dashboard exposes by default. Cut to hit length; the commitment is stated but the example is lost.
- **ADR-007** wanted a summary of the specific nine Montana schema pressure points, not just the count. The list lives in `open-questions.md` and in the research documents; ADR-007 points there.
- **ADR-009** wanted to enumerate the current Claude Code plugin convention (skill frontmatter, trigger description design, SKILL.md format). The ADR gestures at it; the detail lives in the plugin itself.

## Items explicitly out of scope for this ADR batch

Per the orchestrator's instructions, ADRs 010–013 (Decomposed Entity Model, Shape C Response Envelope, Draw Mechanics as Sibling Entity, Server Returns Structure) are deferred to a separate batch. The team noted while drafting that several decisions captured in this batch's ADRs operate against reasoning that lives in ADR-010 through ADR-013 — for example, ADR-006 references the v1→v2 schema migration whose reasoning is proper to ADR-010. The team left forward-pointers where natural (e.g., ADR-008 references the v2 response envelope sections) but did not invent reasoning that belongs in the deferred batch. When 010–013 land, some of this batch's Links sections will want a pass to add the forward references.

## Recommended review pass actions

1. Promote all nine from Proposed to Accepted after reading for coherence with `architecture.md`.
2. Update the `adrs/README.md` index Status column from `—` to `Accepted` for ADRs 001–009.
3. Decide on the 500-word target: either accept the 545–627 range as the practical floor, or formally relax the target to 300–650 in the README.
4. When ADRs 010–013 are drafted, add forward-reference links from ADR-006, ADR-008 where the schema-v2 reasoning is load-bearing.
