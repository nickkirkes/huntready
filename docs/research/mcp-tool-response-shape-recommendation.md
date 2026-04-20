# MCP Tool Response Shape — Recommendation

**Tool:** `get_regulations(lat, lng, species, date)`
**Server:** HuntReady MCP
**Status:** Decision-ready
**Author:** API design synthesis, drawing on two upstream analyst reports (see References)

---

## Landscape summary

Production MCP servers that expose domain-rich data converge on two things and diverge on a third. They converge on *structured envelopes* — the well-regarded servers (Stripe, Linear, Sentry, CARTO, the official Memory server) return a top-level object with semantic keys rather than a bare array, and they universally emit both `content` (human-readable fallback) and `structuredContent` (typed payload) when an `outputSchema` is declared. They converge on *inline provenance* — citations, source URLs, publication dates, and authority identifiers live in the primary data structure, not in a metadata footnote. They diverge on whether semantic sections that don't apply to a given query should be *omitted* from the response or *present-but-null*. Servers whose primary job is search-and-iterate (Linear issues, Stripe charges) tend to omit; servers whose primary job is context-assembly for a specific subject (Sentry issue detail, Memory graph read) tend to present-but-null.

For the frontend, the evidence is less ambiguous. Production UIs that render authority-heavy content against variable data coverage — eCFR, the Federal Register, Westlaw, Casetext, Stripe's API reference, Redfin's property panel — all hold the visual structure stable across data states and render explicit "not applicable" or "unknown" affordances into slots that never disappear. None of them reshape the panel based on what the backend happened to return. This pattern has a direct implication for the response shape: the API should give the UI a stable frame, not a variable one. The dual-consumer requirement (agentic + web) does not split the decision; it reinforces it. Agentic clients benefit from the same named, always-present slots because they make probing reliable ("does `response.seasons.status === "in_season"`?") rather than filter-and-group-dependent.

---

## Candidate shape walkthroughs

The three candidates are stated precisely so the walkthroughs have a fixed target:

**Shape A.** `regulations: Regulation[]` at the top level. Each record carries its own `type` discriminator, its own `source`, and its own rule text. The consumer filters and groups.

**Shape B.** Envelope of named sections: `{ overview, seasons, tags, methods, reporting, contacts, sources }`. Sections that don't apply are *omitted* — absent keys in the JSON.

**Shape C.** Same envelope as Shape B, but every section key is *always present*. Sections that don't apply are `null`; sections that apply but have no data carry an explicit "not applicable" or "unknown" status; sections that apply carry structured content. The UI and agent both render against a fixed frame.

Each shape is walked through against one stress-test scenario. The three scenarios from the brief are: (a) an agentic client answering "can I hunt elk here on Oct 15," (b) the Next.js sidebar rendering the response, (c) a consumer discovering the species isn't in the dataset.

### Shape A against scenario (a): agentic "can I hunt elk here on Oct 15"

The agent receives an array of eight to fifteen regulation objects. Each has a `type` field — `"season_window"`, `"tag_requirement"`, `"method_restriction"`, `"reporting_rule"`, and so on — and each carries its own `source`. To answer the user's question the agent must first reason about grouping: which records concern seasons, which concern tags, which concern methods. Then, inside the season group, it must find the record whose `date_range` brackets Oct 15, check its `status`, and decide whether any unit-specific record overrides. The grouping logic is implicit in the array; the agent infers it from the `type` discriminator and hopes the discriminator set is exhaustive.

This works for a well-behaved query. It fails badly when the dataset is partial. If the array contains two season windows but no tag records, the agent cannot tell whether tags aren't required or whether tag data is simply missing. The absence of a `type: "tag_requirement"` record is ambiguous — it is a shape that cannot distinguish "no tag required" from "we don't know." The agent must either over-hedge ("you may or may not need a tag") or under-hedge (silently assume no tag), and both are wrong. The same array pattern also makes the answer format less reliable: the model may surface the most textually dense record rather than the one that actually answers the question.

Honest assessment: Shape A is defensible only if every regulatory concern is guaranteed to produce at least one record per query, which HuntReady cannot promise across states and species. It pushes grouping and coverage-judgment onto the consumer, and it scatters authority across records in a way that makes the web UI's "show all sources" surface redundantly noisy. It is the wrong shape for this tool.

### Shape B against scenario (b): Next.js sidebar rendering

The sidebar is structured around named cards — Seasons, Tags, Methods, Reporting, Contacts — each with its own header, body, and citation footer. With Shape B, the component tree looks clean at first: `data.seasons && <SeasonsCard data={data.seasons} />`, one line per section. When `data.seasons` is present, the card renders. When it's absent, the card does not render.

The trouble is that "absent" means two different things at the data layer and they collapse to the same condition at the rendering layer. For Montana elk in Unit 410 on Oct 15, the response might omit `reporting` because no reporting is required. For Colorado elk in a unit that's incompletely ingested, the response might also omit `reporting` because it hasn't been processed yet. The UI renders both cases identically — the Reporting card simply isn't there — which is wrong: in the first case the user should see "No reporting required" and in the second they should see "Reporting requirements not yet available for this unit." Shape B cannot encode the difference without either smuggling it into a neighboring field (ugly) or adding a parallel `coverage` object that redundantly lists which omissions were meaningful (ugly in a different way).

A second problem surfaces under streaming. Next.js 14+ encourages each sidebar card to live inside its own Suspense boundary. With Shape B, the boundaries are conditionally mounted based on the shape of the response — the skeleton tree has to be computed from the response keys, which defeats the point of a skeleton that renders *before* the response arrives. Deep linking (`#tags`, `#reporting`) is similarly fragile: a URL that anchors to a section may work one day and 404-scroll the next.

Honest assessment: Shape B is an improvement on Shape A but inherits the ambiguity of absence. It works if the product never needs to distinguish "doesn't apply" from "not in our dataset," which HuntReady does need to distinguish. The architectural commitment to authority preservation makes the distinction load-bearing: a hunter who sees no reporting card must know whether that means "you're free" or "we don't know."

### Shape C against scenario (c): species not covered

A user drops a pin in Wyoming and selects "pronghorn." HuntReady's V1 ingests Montana and Colorado; Wyoming isn't in the corpus. With Shape C, the response shape is unchanged from a fully-covered query. Every section key is present. The overview decision is `"insufficient_data"`; the overview headline is a single sentence explaining that HuntReady doesn't cover Wyoming yet. The `meta.coverage` block carries explicit `jurisdiction: "none"` and `species: "unknown"` signals. Every section (`seasons`, `tags`, `methods`, `reporting`, `contacts`) is `null`. The `sources` array is empty. No fields are missing.

The web UI renders this cleanly without conditional branching. Each card component receives a null payload and draws its own "We don't have this yet" affordance. The hero area reads from `overview.headline` and surfaces the decision visibly. The sidebar frame is identical in shape to the Montana-Unit-410 case, which means skeleton loading, Suspense boundaries, and deep-link anchors all keep working. The agentic client reads `overview.decision === "insufficient_data"` and answers in one turn: "HuntReady doesn't cover Wyoming yet — here's the state agency's page to check directly." It does not infer from absence; it reads an explicit signal.

Honest assessment: Shape C makes the coverage-gap case trivially safe, which is the strongest kind of safety in a regulatory product. The cost is payload size — the response always carries the shape of a fully-populated answer even when most of it is null — and a small amount of template discipline on the server to always produce the frame. Neither cost is meaningful at HuntReady's scale.

---

## Recommendation

**Shape C.** Structured envelope with explicit null-or-empty sections, present on every response.

The TypeScript interface is in the next section. The shape composes a top-level `query` echo, a resolved `jurisdiction` block, a derivative `overview` (short natural-language summary plus a machine-readable decision field), five always-present regulatory sections (`seasons`, `tags`, `methods`, `reporting`, `contacts`), a roll-up `sources` array, and a `meta` envelope carrying schema version, data freshness, coverage signals, and warnings. Each section that applies carries its own inline `source` citation. The envelope is returned as `structuredContent` on the MCP tool response, with a human-readable markdown rendering emitted in `content[0].text` for agentic clients that don't parse structured payloads.

## Rationale

The decision resolves once you stop treating `get_regulations` as a search endpoint and start treating it as a context-assembly endpoint. A search endpoint takes a query and returns whatever matches; it is native to flat arrays with envelope metadata because the consumer is iterating and paginating. A context-assembly endpoint takes a subject (a point, a species, a date) and returns a view of everything the consumer needs to decide about that subject; it is native to named slots because the consumer is reading and reasoning, not iterating. HuntReady's tool is the second kind, and the storage layer's full SQL access makes that choice cheap: the server assembles the view once per query rather than asking the consumer to assemble it from a row set.

The dual-consumer constraint, which initially looked like a reason to compromise, actually reinforces Shape C. Agentic clients benefit from the same named, always-present slots that the web UI needs, but for a different reason. An agent answering "can I hunt elk here on Oct 15" probes the response along a fixed path — is seasons in season, is a tag required, is the method allowed, is reporting required — and each probe is a single structured lookup. Shape C turns the agent's reasoning into a series of reliable field accesses instead of a grouping exercise over an array. The MCP ecosystem evidence that looked like it favored envelopes-with-arrays is really two different patterns mashed together: Stripe and Linear return arrays because their consumers are iterating over issues or charges; Sentry and Memory return envelopes with named fields because their consumers are reading a context. The right ecosystem analog for HuntReady is Sentry's issue detail, not Linear's issue search.

Authority preservation seals the call. HuntReady's architectural commitment is that every regulation reference surfaces its source URL, publication date, and verbatim text prominently. Shape C gives citations a natural home *inside each section* — the seasons card carries its own source, the tags card carries its own source, and the envelope-level `sources` array is the deduplicated roll-up for a "Sources" footer. Shape A distributes citations across individual records (redundant), and Shape B's omission pattern means the absence of a section means the absence of its citation, which silently weakens the authority claim of the whole response. The verbatim rule text — the text the state agency actually published — lives inline with the section that depends on it, so a claim and its citation are never separated in flight.

Finally, Shape C is the most resilient to schema evolution. HuntReady will add regulatory concerns over time — boundary buffer rules, daily limits, harvest notification, drone restrictions — and each addition in Shape C is a new key that defaults to `null` on older data. Consumers that don't know about the new field keep working unchanged; consumers that do know about it read the new slot just like the existing ones. In Shape A, new regulatory concerns require new `type` discriminators and updated grouping logic in every consumer. In Shape B, adding a section that is sometimes-omitted and sometimes-present creates a third ambiguity (was it omitted because it doesn't apply, because we don't know, or because the client hasn't upgraded?). Shape C's rule — every section always present, meaning encoded by status — absorbs the new field without a semantic fork.

## Tradeoffs accepted

Shape C produces a larger payload than the alternatives. A typical Montana-elk query carries every section populated and will run in the single-digit kilobytes range. A Wyoming-pronghorn coverage-gap query carries a nearly-empty envelope that still takes a kilobyte or two. For a tool that is called at human interaction speed, not at bulk-data speed, this is a non-issue, but it is a real cost that needs to be named. A production MCP server at scale might eventually want a `view=compact` request parameter that drops null sections for token-sensitive agents; the envelope structure supports this without schema change.

Shape C imposes template discipline on the server. Every tool invocation must produce every key, which means the query handler cannot short-circuit when a lookup returns empty — it must construct the null-bearing envelope explicitly. In TypeScript this is a one-time builder function and is not a maintenance burden, but it does mean the handler is not a thin wrapper over a SQL result set. Given that the architecture already commits to pre-composited responses, this is a cost that was going to be paid regardless.

The `overview` field introduces a derivative summary that can drift from the structured sections if the derivation logic is sloppy. If the seasons section says the season is closed but the overview headline says "in season," the response is internally inconsistent and the consumer sees contradictory signals. The discipline is that the overview is *always* derived from the structured sections within the same handler call, never stored, and never constructed in a separate path. This is enforceable by tests and by construction (the overview builder takes the structured envelope as input), but it is a real invariant that has to be maintained. The alternative — no overview field at all — is honestly defensible, and an open question below flags whether the web UI benefits from the hero text enough to justify the invariant.

The coverage signals (`meta.coverage.jurisdiction`, `meta.coverage.species`, `meta.coverage.overall`) are slightly redundant with the combination of `resolved.jurisdiction === null` and every-section-null. The redundancy is deliberate: the explicit signals let agents and UI code make decisions without traversing the envelope. The cost is that three places have to agree. If they disagree, the explicit signals in `meta.coverage` are the source of truth and the nulls are a consequence.

## Proposed TypeScript interface

The interface below is the `structuredContent` payload of the MCP tool response. A separate `content: [{type: "text", text: "..."}]` field carries a markdown rendering of the overview plus decision data, for agentic clients that do not parse `structuredContent`. All dates are ISO 8601. All URLs are absolute.

```typescript
/**
 * The complete response shape for `get_regulations(lat, lng, species, date)`.
 * Every top-level key is always present. Sections that do not apply carry
 * `null`; sections that apply carry a structured object with its own `status`
 * enum and inline `source` citation.
 */
export interface GetRegulationsResponse {
  query: {
    lat: number;
    lng: number;
    species: string;      // as supplied by the caller
    date: string;         // ISO date (YYYY-MM-DD)
  };

  /**
   * What HuntReady resolved the query to. A null here means the query could
   * not be placed in a covered jurisdiction or the species could not be
   * canonicalized; see `meta.coverage` for the explicit signal.
   */
  resolved: {
    jurisdiction: {
      state: string;      // ISO-3166-2, e.g. "US-MT"
      unit: string | null;
    } | null;
    species_canonical: string | null;  // e.g. "cervus_canadensis"
    season_cycle_year: number | null;  // e.g. 2026
  };

  /**
   * Derivative, always-consistent summary. Built from the structured sections
   * below within the same handler call; never persisted; never a source of
   * truth. Agents should feel free to use `overview.decision` and
   * `overview.headline` directly; both are safe to surface to end users.
   */
  overview: {
    decision: "permitted" | "prohibited" | "requires_action" | "insufficient_data";
    headline: string;     // one-sentence answer, human-readable
    caveats: string[];    // short qualifiers, max ~3 entries
  };

  seasons:   SeasonsSection   | null;
  tags:      TagsSection      | null;
  methods:   MethodsSection   | null;
  reporting: ReportingSection | null;
  contacts:  ContactsSection  | null;

  /**
   * Deduplicated roll-up of every citation referenced by any populated
   * section above. Empty array when there is no covered data for this query.
   */
  sources: Citation[];

  meta: {
    schema_version: number;
    generated_at: string;              // ISO 8601 timestamp
    data_freshness: {
      most_recent_source_date: string; // ISO date
      stalest_source_date: string;     // ISO date
      is_stale: boolean;               // true if any cited source > 180 days
    };
    coverage: {
      jurisdiction: Coverage;
      species:      Coverage;
      overall:      Coverage;          // worst of the above
    };
    warnings: Warning[];               // [] when none
  };
}

export type Coverage =
  | "full"          // HuntReady has complete data for this dimension
  | "partial"       // some known, some not
  | "none";         // not in our dataset

export interface SeasonsSection {
  status: "in_season" | "out_of_season" | "no_season_defined" | "unknown";
  /** All season windows that touch the query date's calendar year for this
   *  species and jurisdiction, weapon-type-stratified. Empty array is valid. */
  windows: SeasonWindow[];
  source: Citation;   // most-specific citation for the status claim
}

export interface SeasonWindow {
  opens: string;                                       // ISO date
  closes: string;                                      // ISO date
  weapon_type: string | null;                          // "archery" | "rifle" | ...
  residency: "resident" | "non-resident" | "both" | null;
  verbatim_rule: string;                               // direct quote from source
  page_reference: string | null;
  confidence: "high" | "medium" | "low";
  source: Citation;
}

export interface TagsSection {
  required: boolean;
  tag_type: "general" | "limited_draw" | "over_the_counter" | "none";
  application_deadline: string | null;  // ISO date
  purchase_url: string | null;          // direct link to state agency flow
  verbatim_rule: string;
  confidence: "high" | "medium" | "low";
  source: Citation;
}

export interface MethodsSection {
  allowed: string[];       // e.g. ["archery", "muzzleloader"]
  prohibited: string[];    // e.g. ["crossbow"]
  verbatim_rule: string;
  confidence: "high" | "medium" | "low";
  source: Citation;
}

export interface ReportingSection {
  required: boolean;
  deadline: string | null;              // e.g. "48 hours after harvest"
  submission_method: "online" | "phone" | "in_person" | "mail" | null;
  submission_url: string | null;
  verbatim_rule: string;
  confidence: "high" | "medium" | "low";
  source: Citation;
}

export interface ContactsSection {
  regional_warden: Contact | null;
  regional_office: Contact | null;
  rules_hotline:   Contact | null;
}

export interface Contact {
  role: string;
  name: string | null;
  phone: string | null;
  email: string | null;
  url: string | null;
  source: Citation;
}

export interface Citation {
  id: string;               // stable ID for deduplication across sections
  agency: string;           // e.g. "Montana FWP"
  title: string;            // e.g. "2026 Montana Hunting Regulations"
  url: string;
  publication_date: string; // ISO date
  document_type: "annual_regulations" | "rule_change" | "emergency_order";
  page_reference: string | null;
}

export interface Warning {
  code:
    | "STALE_SOURCE"
    | "LOW_CONFIDENCE"
    | "CONFLICTING_RULES"
    | "PENDING_CHANGE"
    | "BOUNDARY_AMBIGUOUS";
  section: "seasons" | "tags" | "methods" | "reporting" | "contacts" | "overall";
  message: string;          // human-readable, safe to display
}
```

## Open questions flagged for later

The following questions could not be fully resolved by the research and should be decided before or during implementation. None of them block the Shape C recommendation.

The first is whether `overview` is worth the derivation discipline it requires. The research supports it — every authority-heavy UI in the frontend survey has a hero element, and agentic clients benefit from a one-field decision — but a rigorous derivation path is a real invariant to maintain. An alternative is to drop `overview` from the envelope and let the web UI compose the headline from structured sections (and let agents do the same). Decide based on whether the Next.js sidebar team wants a server-composed hero. Recommend: keep `overview`, enforce derivation via a builder function and unit tests, revisit if drift bugs show up in V1.

The second is whether methods-of-take should be a flat `allowed: string[]` or a richer structure that encodes weapon-specific restrictions (broadhead diameter, draw-weight minimum, magazine capacity). The current interface captures the common case cleanly but flattens real regulatory complexity. For Montana and Colorado V1, `allowed`/`prohibited` is sufficient; Colorado archery specifically has draw-weight rules that will force a richer shape by V2. A `MethodDetail[]` variant is easy to add as a parallel optional field when needed.

The third is the granularity of the `Citation.id`. The current interface treats citations as referenceable by a stable ID so the envelope-level `sources` array can dedupe against inline section sources. The question is whether the ID should be scoped to the source document (one ID per publication) or to the section-within-a-document (one ID per cited passage). The latter is more precise but requires the ingestion pipeline to assign stable passage-level IDs, which is a non-trivial tracking problem for PDFs. Recommend document-level IDs for V1 with `page_reference` as the sub-document locator; revisit if the web UI needs to highlight specific passages.

The fourth is whether `meta.coverage` should include a free-form `coverage_notes: string | null` for operational communication ("Colorado rules published 2026-03-14, ingested 2026-03-20; minor pending corrections"). This is useful for the web UI's staleness indicator and for agent transparency, but it is prose — easy to inject inconsistency through. Recommend adding it only if an operational story emerges that the current `data_freshness` and `warnings` blocks cannot express.

The fifth is the MCP protocol question of whether `content[0].text` should carry a markdown rendering of the full response (for agents that don't parse `structuredContent`) or only the overview plus the decision. Full rendering is useful for tool-use training and for older clients; minimal rendering is cheaper in tokens and avoids duplicating the structured data at two different sources of truth. Recommend: overview-plus-decision in `content`, full structured data in `structuredContent`, with an explicit note in the tool description that structured consumers should prefer `structuredContent`.

---

## References

Upstream research that informed this recommendation lives alongside in the same folder:

- `mcp_response_shape_analysis.md` — survey of eight production MCP servers (Memory, Filesystem, Stripe, Linear, Medical-MCP, Jira/Atlassian, CARTO, GitHub) with response-shape patterns, citation handling, and empty-state treatments.
- `response-shape-analysis.md` (frontend) — survey of ten production UIs rendering regulatory and legal data (OnX Hunt, HuntWise, Westlaw, Casetext, eCFR, Federal Register, CPW, PatternFly, Redfin, Stripe API docs) with per-UI notes on sidebar structure, citation rendering, and empty-state affordances.

The architectural context for this tool, including the canonical `RegulationRecord` interface in storage, is documented in `docs/architecture.md` — in particular the "Authority is preserved, not replaced" commitment, which this response shape is designed to enforce.
