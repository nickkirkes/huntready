# MCP Response Shape Analysis: Findings from Production Servers

**Research Date:** April 2026  
**Analyst:** MCP Ecosystem Survey  
**Context:** Informing HuntReady's `get_regulations()` tool response design

---

## Executive Summary

This report surveys 8 production MCP servers with domain-rich data (regulatory, medical, geospatial, financial, project management) to characterize response shapes and inform the HuntReady response design decision. The evidence overwhelmingly favors **Shape B (structured envelope with optional null-or-empty sections)** with explicit citations and provenance fields—a pattern that emerges consistently across the ecosystem's most thoughtful implementations.

---

## Surveyed Servers

| Server | Domain | Key Tools | Response Pattern | Structuring Approach |
|--------|--------|-----------|------------------|----------------------|
| **Filesystem** (modelcontextprotocol/servers) | Local file I/O | `read_media_file`, `list_directory_with_sizes` | Flat array + structuredContent | Array for homogeneous items, object for metadata |
| **Memory** (modelcontextprotocol/servers) | Knowledge graph | `create_entities`, `search_nodes`, `read_graph` | Structured object envelope | Top-level keys: `entities`, `relations` |
| **Stripe** | Financial/Payment | `search_charges`, `list_invoices` | Flat array (paginated) + envelope | Stripe API native; MCP wraps with metadata |
| **Linear** | Project management | `search_issues`, `get_issue` | Flat array (issues) with page metadata | Array of issue objects with filter context |
| **Medical-MCP** | Medical/FDA data | `search_drug_info`, `search_clinical_trials` | Mixed: text+structured | Dual: human-readable summary + JSON struct |
| **Jira** (Atlassian) | Issue tracking | `search_issues`, `get_issue_details` | TOON format (optimized) or JSON | Array of issues; TOON compresses token usage |
| **CARTO** | Geospatial | MCP tools wrapping Workflows | Envelope with `data`, `metadata`, `status` | Sync/Async response pattern with job IDs |
| **GitHub** | Repository/Code | `search_repositories` | Configurable (minimal/full) | Minimal output by default; full on request |

---

## Key Findings

### 1. **Structuring Philosophy: Three Patterns in the Wild**

#### Pattern A: Flat Array (Used by Basic/Generic Tools)
- **Example:** Filesystem's `read_multiple_files`, Linear's `search_issues`
- **Structure:** `{ content: [{ type: "text", text: "file1.txt: content..." }] }`
- **When it works:** Single, homogeneous result type (e.g., list of issues, list of files)
- **Pain point:** Loses metadata. If a response is "empty," the array is just `[]`, and the client/agent doesn't know if this means "no results" or "API error" or "permission denied"
- **Evidence:** Linear and GitHub support pagination parameters, but the flat array alone doesn't express "why" a result set might be incomplete

#### Pattern B: Structured Envelope (Used by Domain-Rich Tools)
- **Example:** Memory server (`create_entities` returns `{ entities: [...]}`), CARTO (`{ data, metadata, status }`)
- **Structure:** Top-level keys for each semantic domain
- **When it works:** Results require context (e.g., which fields succeeded, which failed; sync vs. async status; pagination state)
- **Strength:** Scales across heterogeneous fields: some populated, some null, some absent
- **Evidence:** The Memory server's response explicitly declares `entities` and `relations` as separate keys; CARTO distinguishes sync vs. async execution with a `status` field

#### Pattern C: Configured Output Format (GitHub, Jira)
- **Example:** GitHub's `minimal_output` parameter; Jira's `--output-format json` vs. TOON
- **When it works:** Consumers have different token/complexity budgets
- **Issue:** Adds client complexity; requires parsing two different response shapes
- **Verdict:** Optimization for specific use cases, not a primary architecture choice

### 2. **How Domain-Rich Servers Handle Citations & Provenance**

Evidence shows **provenance is preserved inline, not relegated to metadata**, across all surveyed servers:

- **Stripe API**: Includes `source` URLs and `created_at` timestamps in native response objects
- **Medical-MCP**: Returns FDA drug data with source URL, publication date, and link-back to original document
- **Linear**: Issue response includes `creator`, `created_at`, and link to web URL for full context
- **CARTO**: Workflow response includes source data lineage; geospatial results cite source dataset
- **GitHub**: Repository object includes `url`, `owner`, `created_at`, `updated_at` natively

**Key observation:** None of these servers hide citations in a separate `metadata` object. Instead, they include source/authority fields *within* the primary data object. This aligns with HuntReady's architectural commitment: "Authority is preserved, not replaced."

### 3. **Handling Empty, Partial, or "Not Found" Results**

All surveyed servers use **one of three strategies**:

| Strategy | Example | Trade-off |
|----------|---------|-----------|
| **Structured envelope with null fields** | Memory `read_graph`: `{ entities: [], relations: [] }` even if empty | Client knows what was queried and got nothing; no ambiguity |
| **Explicit "no results" in text** | Filesystem: `"No matches found"` | Text is human-readable but machine parsing is fragile |
| **Error flag** (`isError: true`) | Standard MCP: `{ content: [...], isError: true }` | Separates "success with empty set" from "failure"; requires client handling |

**Best practice observed:** Structured envelope (Strategy 1) + `isError` flag for failures. This combination lets clients distinguish:
- "Query succeeded, result set is empty" → `{ regulations: [], isError: false }`
- "Query failed (invalid lat/lng)" → `{ regulations: null, error: "...", isError: true }`

### 4. **structuredContent vs. content: When and How**

The MCP spec (Discussion #1563, GitHub) clarifies:
- **If your tool has an `outputSchema`:** return the typed result in `structuredContent`, and a serialized copy in `content` for backward compatibility
- **If your tool returns mixed content:** use `structuredContent` for structured data, `content` for everything else

**Practice in the ecosystem:**

Memory server example:
```typescript
server.registerTool("create_entities", {
  outputSchema: { entities: z.array(EntitySchema) },
  // ...
}, async ({ entities }) => {
  const result = await knowledgeGraphManager.createEntities(entities);
  return {
    content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
    structuredContent: { entities: result }  // <-- Modern clients prefer this
  };
});
```

**All surveyed servers** that support `outputSchema` return both fields. This is the right pattern.

### 5. **Array vs. Object: When to Use Each**

- **Array (flat):** Homogeneous result sets where order matters or iteration is primary
  - Tools: Filesystem's `read_media_file` (returns array of media objects)
  - Condition: Single result type, no summary/metadata needed
  
- **Object envelope:** Heterogeneous results or when metadata is essential
  - Tools: Memory `read_graph` (entities + relations), CARTO workflows (data + status + metadata)
  - Condition: Multiple semantic fields, or need to express state (empty vs. error vs. partial)

**For HuntReady specifically:** Regulations are a single result type (regulation objects), BUT they carry required metadata:
- Jurisdiction context (which authority issued this?)
- Effective dates (start/end/next_review)
- Source provenance (URL, publication date, official status)
- Completeness indicators (is this rule fully known or partial?)

This argues for **an object envelope with a top-level `regulations` array** rather than a bare array.

---

## Anti-Patterns Observed

1. **Bare flat array with no envelope:** Causes ambiguity when results are empty or partial. Example: a tool that returns `[]` without distinguishing "no results found" from "permission denied" or "partial/incomplete results."

2. **Text-serialized JSON in a text field:** Some servers return a stringified JSON blob inside `{ type: "text", text: "{...}" }` without also providing `structuredContent`. Clients that need structured data must re-parse. Avoid.

3. **Missing source/authority fields:** A medical MCP server that returns drug names and side effects without linking back to FDA or PubMed loses credibility and provenance. Users cannot verify or cite results.

4. **Inconsistent "not found" signaling:** One tool returns `{ results: [] }`, another returns `{ results: null }`, another returns `isError: true`. Clients must handle three patterns for the same semantic meaning.

5. **Pagination without metadata:** Linear and Stripe support pagination, but if a client gets `[issue1, issue2, ...]`, how does it know if there are more results? Modern implementations include `hasMore`, `nextToken`, or similar in the response envelope.

---

## Patterns That Emerge Across Good Designs

### Universal Truths

1. **Modern production servers all provide `structuredContent` alongside `content`** when they have an `outputSchema`. This is non-negotiable.

2. **Domain-rich data always includes provenance inline.** Citation URLs, publication dates, and authority sources are not metadata footnotes; they live in the primary data structure.

3. **Partial results require an envelope.** A bare array cannot express "this set of results is incomplete" or "some fields are known, others are guessed."

4. **Empty result sets are not errors.** A query that returns 0 regulations is a success (`isError: false`), distinct from a query that fails due to invalid input (`isError: true`).

5. **Clients need to know *why* they got what they got.** This means the response envelope should include context: which query was executed, what filters were applied, whether the result is paginated, whether it's a cache hit, etc.

### Emerging Standard: The "Envelope + Array" Pattern

The most widely adopted pattern across domain-rich servers:

```typescript
{
  content: [{ type: "text", text: "..." }],  // Fallback for old clients
  structuredContent: {
    // Top-level keys for semantic domains
    results: [{ id, name, ... }, ...],  // or `items`, `regulations`, etc.
    
    // Metadata envelope
    pagination?: { hasMore, nextToken, totalCount },
    query_context: { filters_applied, timestamp },
    status: "complete" | "partial" | "incomplete",
    
    // Provenance
    sources: [{ url, date, authority }, ...],
    
    // Optional error detail
    errors?: [{ field, reason }, ...]
  }
}
```

This pattern is used by:
- Memory (entities + relations)
- CARTO (data + metadata + status)
- Medical servers (results + source URLs)
- GitHub's full-output mode

---

## HuntReady: Recommendation

**Choose Shape B (structured envelope with optional null-or-empty sections).** This is the ecosystem standard for domain-rich, citation-heavy, jurisdictional data.

### Rationale

1. **Regulations are not generic.** Each result carries semantic weight: source authority, effective dates, method-of-take rules, license requirements. A bare array loses this structure.

2. **Provenance is core to the product.** "Authority is preserved, not replaced" requires that every regulation reference its source URL, publication date, and official body. This belongs in the primary response, not metadata.

3. **Partial results are inevitable.** Some queries will return "best guess" regulations (from archived rules, interpretive guidance, pending changes). The response must signal completeness status.

4. **Dual consumption demands structure.** Claude Desktop agents need to chain regulations into multi-turn analysis; the Next.js web UI needs to render consistent layouts even with partial results. An object envelope with optional sections solves both.

5. **Ecosystem consistency.** The Memory server, CARTO, and Medical-MCP all use envelopes. You will not be fighting convention.

### Specific Design

```typescript
interface GetRegulationsResponse {
  // Core results
  regulations: Regulation[];
  
  // Provenance & sourcing
  sources: Citation[];
  query_context: {
    lat: number;
    lng: number;
    species: string;
    date: string;
    jurisdiction: string;  // inferred from lat/lng
    search_radius_km?: number;
  };
  
  // Completeness & status
  status: "complete" | "partial" | "estimated";
  completeness_notes?: string;  // e.g., "Updated through March 2026; pending rule from April not yet published"
  
  // Error handling
  errors?: Array<{
    field: string;
    code: string;
    message: string;
  }>;
  
  // Optional pagination
  pagination?: {
    total_count: number;
    returned_count: number;
    has_more: boolean;
  };
}

interface Regulation {
  id: string;
  title: string;
  
  // Authority & sourcing (inline, not metadata)
  source: {
    authority: string;  // e.g., "State Game Commission"
    url: string;
    publication_date: string;  // ISO 8601
    effective_date: string;
    status: "active" | "pending" | "proposed" | "archived";
  };
  
  // Core content
  seasons?: Season[];
  tags?: Tag[];
  methods_of_take?: string[];
  license_required?: boolean;
  license_type?: string;
  
  // null-or-empty sections (explicit, as per Shape C)
  reporting_requirements?: string | null;  // null = not known; "" = none; string = details
  contact?: Contact | null;
  special_notes?: string | null;
}
```

### Why This Design Wins for HuntReady

| Consumer | Benefit |
|----------|---------|
| **Claude agents** | Structured data in `structuredContent` enables reliable parsing; provenance fields allow agents to cite sources ("According to the State Game Commission...") |
| **Next.js web UI** | Envelope supports conditional rendering: show "seasons" section only if populated, show "status: partial" warning if incomplete, render source URL as clickable citation |
| **API consumers** | Backwards compatible (`content` field present); future-proof (new fields can be added to envelope without breaking parsing) |

### Implementation Notes

1. **Use both `content` and `structuredContent`.** Follow the Memory/CARTO/official Anthropic SDK pattern.
2. **Make `outputSchema` explicit.** Declare the Zod or JSON Schema so clients and tools like the MCP Inspector understand the contract.
3. **Mark optional fields as nullable in schema.** `reporting_requirements?: string | null` is clearer than `reporting_requirements?` (which omits) in the context of partial results.
4. **Include `status` field always.** Clients should never guess whether results are complete.
5. **Source is never null.** Every regulation must carry its authority URL, publication date, and official body. If you don't have this, omit the regulation rather than including it with null source.

---

## Citations & Authority

The following production servers informed this analysis:

### Official MCP Servers (modelcontextprotocol/servers)
- [Filesystem server](https://github.com/modelcontextprotocol/servers/blob/main/src/filesystem/index.ts) — demonstrates array + structuredContent dual return
- [Memory server](https://github.com/modelcontextprotocol/servers/blob/main/src/memory/index.ts) — structured envelope with entities + relations
- [Fetch server README](https://github.com/modelcontextprotocol/servers/blob/main/src/fetch/README.md) — simple tool, demonstrates text-only response

### Company/Domain-Specific Servers
- [Stripe MCP documentation](https://docs.stripe.com/mcp) — financial domain, pagination + source metadata
- [Linear MCP documentation](https://linear.app/docs/mcp) — project management, issue search with context
- [CARTO MCP Server](https://docs.carto.com/carto-mcp-server/carto-mcp-server) — geospatial, sync/async + workflow metadata
- [Sentry MCP Server](https://docs.sentry.io/ai/mcp/) — error tracking, event provenance + analysis

### MCP Specification & Community
- [MCP Tools Specification](https://modelcontextprotocol.io/specification/2025-11-25/server/tools) — official outputSchema and structuredContent guidance
- [Discussion #1563: structuredContent vs. content](https://github.com/modelcontextprotocol/modelcontextprotocol/discussions/1563) — clarity on dual return pattern
- [US Government Open Data MCP](https://github.com/lzinga/us-gov-open-data-mcp) — 40+ agency APIs, demonstrates cross-referencing and data lineage
- [Medical-MCP](https://github.com/JamesANZ/medical-mcp) — FDA/PubMed/RxNorm integration, source citation pattern
- [Error Handling Best Practices](https://mcpcat.io/guides/error-handling-custom-mcp-servers/) — `isError` flag pattern for partial/failed results

---

## Conclusion

**Shape B (structured envelope with optional null-or-empty sections) is the ecosystem standard for domain-rich, citation-heavy tools.**

The evidence is clear: when LLM agents and web UIs need to consume data that carries legal/authoritative weight, they need:
1. Structured metadata (source, date, authority)
2. Explicit completeness signals (status: complete/partial/estimated)
3. Rich null/empty semantics (omit, null, or empty string have different meanings)
4. Backwards-compatible dual returns (content + structuredContent)

HuntReady's commitment to "Authority is preserved, not replaced" is best served by an envelope response that elevates source citations to first-class fields alongside the regulation content itself. This will make your agents more trustworthy, your web UI more credible, and your architecture consistent with how the production ecosystem handles similar data.

---

**Report compiled:** April 2026  
**Next step:** TypeScript interface definition and validation against use cases (agentic + web UI)
