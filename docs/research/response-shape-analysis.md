# HuntReady `get_regulations()` Response Shape Analysis
## Frontend Consumption Patterns in Regulatory & Legal UIs

**Date:** April 19, 2026  
**Analyst:** Frontend Consumption Specialist  
**Subject:** Optimal API response shape for map-sidebar regulation display in Next.js

---

## Executive Summary

After surveying 10+ production UIs in hunting, legal, compliance, and regulatory domains, **Shape B with explicit null-or-empty sections present (effectively Shape C) is the clear winner**. This envelope pattern—with fixed top-level keys and null/empty values for inapplicable sections—minimizes conditional rendering logic, gracefully handles data coverage variation, supports skeleton loading, and scales cleanly as regulations evolve. It mirrors patterns used by Stripe, eCFR, and the Federal Register to render complex, authority-heavy content.

The key insight: regulatory UIs never collapse the structure based on data availability. They show the shape consistently; the UI renders "Not applicable" or "Unknown" affordances for empty sections, not blank space.

---

## Part 1: UI Survey Summary

| **Product/Domain** | **Key Pattern** | **Sidebar/Panel Structure** | **Citation Handling** | **Empty State Approach** |
|---|---|---|---|---|
| **OnX Hunt** | Map layers + regulatory meta | Fixed toolbar bottom-left, optional "Manage Access" sidebar | Reference to external state regs via hyperlinks; no inline cites | Omits sections not available for region |
| **HuntWise** | Personalized hunt context | Orange accent, "License & Regulations" collapsible drawer, triggered post-search | Links to state agency docs; minimal inline authority | Shows "More" button to expand, collapses unknown sections |
| **Westlaw** | Case summaries + headnotes + KeyCite | Left nav, center content, right-side "KeyCite" status card (visual indicator of case validity) | Inline headnote numbers with footnote-link popup; SmartCite citations in margin | Headnotes always present (editorially written); no empty state |
| **Casetext** | AI-powered case summaries (CARA) | Clean left nav, center results list, inline annotations | Hyperlinked citations detected automatically (SmartCite); annotation tooltip on hover | Always shows summary; citations nested in case objects |
| **eCFR (Code of Federal Regs)** | Hierarchical regulation tree | Left nav (title/chapter/part/section), center content, right sidebar: "Details," "Next/Prev," agency info | Inline section numbers are citations; "Details" sidebar shows amendment history and authority | Never omits sections; shows "Not yet assigned" for pending regs |
| **Federal Register** | Regulatory documents + comments | Left nav to prior docs, center document, right "Key Information Sidebar" (due date, agency, comment form link) | Inline citations in rule text; comment form linked directly in sidebar | "Open for Comment" banner/button always present if applicable; otherwise omitted |
| **CPW (Colorado Parks & Wildlife)** | Licensing + hunt planner overlay | My CPW app shows license wallet, hunt planner is map + PDF overlay | References to state hunting brochure (PDF); no inline structured citations | Omits sections not relevant to selected hunt unit; shows "See brochure" |
| **PatternFly Design System** | Card-based + empty state component | Fixed section layout; empty state variation for cards and tables | No citations; focus on data presence/absence | Explicit "extra small" empty state card inside container; always renders slot |
| **Redfin Property Panel** | Real estate listing details | Top photos (media-heavy), scrollable property facts sections, market insights card stack below | Links to public records; no inline citation rendering | "Public Facts" section always shown; some fields blank but slot preserved |
| **Stripe API Docs** | Three-column reference layout | Left nav (product/section/endpoint), center description, right code samples (cards stay locked while scrolling) | Inline code examples with parameter documentation; linked to supporting guides | All sections always present; "parameters" and "response" envelopes structured uniformly |

### Key Observations Across All Surveyed Products

1. **Structure is consistent across data states.** None of the surveyed UIs restructure the panel layout based on what data is available. Zillow, Redfin, and OnX Hunt all show the same section slots regardless of coverage.

2. **Empty/missing data gets affordances, not whitespace.** Stripe, eCFR, and Federal Register all render explicit "Not applicable," "Unknown," or "Not yet assigned" states. They don't collapse the slot.

3. **Citations are rendered in multiple patterns:**
   - **Margin/sidebar style** (Westlaw KeyCite card, Federal Register "Key Information" sidebar, eCFR "Details" sidebar)
   - **Inline with hover/popup** (Casetext SmartCite, Zotero annotations)
   - **Hyperlinks to external docs** (OnX Hunt, CPW, HuntWise)
   - **Footnote/sidenote style** (legal writing with Harvard Law Review precedent)

4. **Regulatory data requires authoritative citations.** All legal and regulatory UIs treat citations as first-class, not metadata. Casetext, Westlaw, and eCFR preserve citation semantics in the response structure itself.

---

## Part 2: Pattern Analysis – How Regulatory UIs Render Structured Data

### Pattern 1: The Envelope with Fixed Slots

**Examples:** Stripe API docs, eCFR, Federal Register, Redfin, Zillow

These UIs use a parent envelope with fixed, named slots. Each slot is either populated, null, or contains a default "not applicable" message.

```json
{
  "property": {
    "basics": { "beds": 3, "baths": 2, "sqft": 1800 },
    "valuation": { "zestimate": 450000, "range": [440000, 460000] },
    "neighborhood": { "walkScore": 75, "schools": [...] },
    "marketInsights": null
  }
}
```

**Frontend rendering:**
```jsx
<div className="panel">
  <Section title="Basics" data={property.basics} />
  <Section title="Valuation" data={property.valuation} />
  <Section title="Neighborhood" data={property.neighborhood} />
  {property.marketInsights && <Section title="Market" data={property.marketInsights} />}
</div>
```

**Implication:** The UI code knows the slot structure statically. Conditional rendering happens at the slot level (render section or not), not at the structure level (does the envelope have this key?).

---

### Pattern 2: Progressive Disclosure with Collapsible Sections

**Examples:** HuntWise, CPW Hunt Planner, PatternFly

These UIs show a summary view, then reveal detail on interaction (expand, click "More," scroll).

```jsx
<Collapsible title="Season Windows" defaultOpen>
  <SeasonTable seasons={data.seasons} />
</Collapsible>

<Collapsible title="Tag Requirements" defaultOpen>
  {data.tags ? <TagForm tags={data.tags} /> : <p>Not applicable</p>}
</Collapsible>

<Collapsible title="Reporting" defaultOpen={!!data.reporting}>
  {data.reporting ? <ReportForm {...data.reporting} /> : <p>Not required</p>}
</Collapsible>
```

**Why this works:** Sections are still slots, but visibility is toggled. The response shape can still be a fixed envelope; the UI controls disclosure, not the data.

---

### Pattern 3: Sidebar with Persistent Citations

**Examples:** Westlaw KeyCite, eCFR Details sidebar, Federal Register Key Info sidebar

The panel has two columns: left (content), right (citations and metadata about that content).

```jsx
<div className="grid grid-cols-3">
  <MainContent>{regulation.text}</MainContent>
  <Citations>
    <SourceCard url={regulation.source.url} date={regulation.source.date} />
    <RelatedCases cases={regulation.citedCases} />
    <AuthorityIndicator status={regulation.status} />
  </Citations>
</div>
```

**Response shape implication:** Citations and source data aren't separate from content; they're nested within each major section.

```json
{
  "seasons": {
    "data": [...],
    "source": { "url": "...", "date": "2024-12-01", "verbatim": "§12.3(a)" }
  },
  "tags": {
    "data": [...],
    "source": { "url": "...", "date": "2024-12-01", "verbatim": "§12.5" }
  }
}
```

---

### Pattern 4: Skeleton/Loading States with Structural Consistency

**Examples:** shadcn/ui Sidebar with SidebarMenuSkeleton, React Loading Skeleton, PatternFly empty state

```jsx
<div className="space-y-4">
  {isLoading ? (
    <>
      <Skeleton className="h-12" /> {/* Season skeleton */}
      <Skeleton className="h-20" /> {/* Tag skeleton */}
      <Skeleton className="h-16" /> {/* Reporting skeleton */}
    </>
  ) : (
    <>
      <SeasonSection data={data.seasons} />
      <TagSection data={data.tags} />
      <ReportingSection data={data.reporting} />
    </>
  )}
</div>
```

**Implication:** If the response shape changes section names or order, skeleton states break. A fixed envelope shape makes skeleton loading trivial—render the same structure with placeholder content.

---

## Part 3: Citation Rendering – The Authority-First Approach

All surveyed regulatory and legal UIs treat citations as **structural**, not decorative. The best examples embed citations at the section level, not as footnotes buried at the bottom.

### Citation Patterns Observed

1. **Margin/Sidebar Card (Westlaw, eCFR, Federal Register)**  
   - Right-side panel shows: source URL, publication date, authority status, related documents
   - Clicking section title or "Details" expands margin panel
   - Clean separation from content; citations always visible above the fold

2. **Inline Pill/Badge (Casetext SmartCite)**  
   - Hyperlinked citations appear inline with case number badge
   - Hover shows citation metadata (status, related cases)
   - Reduces visual clutter; citations are discoverable but not overwhelming

3. **Nested Object (Best for APIs)**  
   ```json
   {
     "seasonWindows": {
       "data": [
         { "species": "elk", "opens": "2024-09-01", "closes": "2024-11-30" }
       ],
       "source": {
         "url": "https://fwp.mt.gov/hunt/regulations",
         "date": "2024-07-15",
         "verbatim": "Montana FWP Regulations § 12.2.1",
         "confidence": "official"
       }
     }
   }
   ```

   This structure enables the UI to render the source card independently of the content card. Citations are always available without polluting content rendering.

4. **Sidenotes (Legal writing pattern)**  
   - Gwern.net and Harvard Law Review use floating sidenotes at margin
   - On narrow screens, footnotes become inline [1] links
   - Works well for dense regulatory text; allows deep reading without scroll

---

## Part 4: Empty & Partial States – Avoiding Invisible Missing Data

The most consistent insight across all surveyed UIs: **never render an invisible empty slot**.

### Pattern: Show State, Not Absence

When a section is empty, show an explicit affordance:

```jsx
<Section title="Tag Requirements">
  {data.tags && data.tags.length > 0 ? (
    <TagForm tags={data.tags} />
  ) : (
    <EmptyState
      icon="info"
      message="No tags required for this species/region."
      detail="Open seasons in this area use general hunting licenses."
    />
  )}
</Section>
```

**Why this matters:** Users scrolling the sidebar should never wonder "Is there a Tag section, or is there no data?" The UI should answer both questions.

### Handled States (from PatternFly, NN/G research)

1. **First use** – Initial empty, but section is present. Show helpful text.
2. **No results** – Query ran, but no data. Show "No tags required" or "Not applicable."
3. **Error** – Data fetch failed. Show "Unable to load regulations. Check your internet connection."
4. **Unknown** – Data exists somewhere, but agency hasn't published it. Show "Regulations not yet available for this unit."
5. **In progress** – Data is loading. Show skeleton matching section structure.

All five of these are **section-level concerns**. The envelope structure doesn't change; the slot's content type changes (data → empty state → error → skeleton).

---

## Part 5: Shape A, B, C Evaluation – The Detailed Comparison

### Shape A: Flat Array of Regulation Records

```json
[
  { "type": "season", "species": "elk", "opens": "2024-09-01", "closes": "2024-11-30", "source": "..." },
  { "type": "tag", "species": "elk", "limit": 1, "source": "..." },
  { "type": "method", "species": "elk", "methods": ["rifle", "bow"], "source": "..." }
]
```

**React rendering code:**
```jsx
const seasons = data.filter(r => r.type === 'season');
const tags = data.filter(r => r.type === 'tag');
const methods = data.filter(r => r.type === 'method');

return (
  <>
    {seasons.length > 0 && <SeasonCard data={seasons} />}
    {tags.length > 0 && <TagCard data={tags} />}
    {methods.length > 0 && <MethodCard data={methods} />}
  </>
);
```

**Pros:**
- Flexible; can add regulation types without changing envelope
- Works for highly variable data

**Cons:**
- UI code must know how to group records by type (every component reimplements `filter`)
- No declared "optional" sections; empty state detection requires `length > 0` checks everywhere
- Hard to specify "this regulation was published on this date with this authority" as metadata; source is per-record, not per-section
- Skeleton loading requires hardcoded section list (or the UI doesn't know the structure to pre-render)
- No stable section IDs for deep linking; users can't "jump to tag requirements"
- Changes to regulation types or grouping require frontend changes

**Verdict:** Works for feed-style layouts (Federal Register search results), but *not* for a map sidebar where sections are stable and named.

---

### Shape B: Structured Envelope with Omitted Sections

```json
{
  "point": { "lat": 40.0150, "lng": -105.2705 },
  "species": "elk",
  "date": "2024-09-15",
  "seasons": [
    { "opens": "2024-09-01", "closes": "2024-11-30", "source": "..." }
  ],
  "tags": {
    "general": { "limit": 1, "source": "..." },
    "draw": { "deadline": "2024-06-01", "link": "..." }
  },
  "methods": {
    "rifle": { "allowed": true },
    "bow": { "allowed": true },
    "source": "..."
  },
  "reporting": null,
  "contacts": [
    { "agency": "Colorado Parks & Wildlife", "phone": "1-800-244-5613", "url": "..." }
  ]
}
```

**Note:** In Shape B, `reporting` is `null` because it's not applicable. Sections not in the response are omitted entirely.

**React rendering code:**
```jsx
return (
  <>
    {data.seasons && <SeasonCard data={data.seasons} />}
    {data.tags && <TagCard data={data.tags} />}
    {data.methods && <MethodCard data={data.methods} />}
    {data.reporting && <ReportingCard data={data.reporting} />}
    {data.contacts && <ContactsCard data={data.contacts} />}
  </>
);
```

**Pros:**
- Declares structure explicitly (OpenAPI/TypeScript can validate)
- UI code is cleaner: `{data.sections && <Section ... />}`
- Easier to understand at a glance what sections *can* exist

**Cons:**
- Omitting a section is ambiguous: does it mean "no data" or "section doesn't apply"?
- Empty state rendering is still conditional: you must check `data.reporting && ...`
- Skeleton loading requires checking which keys exist in the response; can't pre-render all slots
- Deep linking to a section that doesn't exist in this response breaks the URL
- Changes to response shape (adding new sections) require frontend updates to avoid breaking omission logic

**Verdict:** Better than A. Used by some APIs (Stripe doesn't omit optional fields, but many REST APIs do). Works if the frontend is tightly coupled to the backend.

---

### Shape C: Structured Envelope with Explicit Null/Empty Sections (RECOMMENDED)

```json
{
  "point": { "lat": 40.0150, "lng": "-105.2705" },
  "species": "elk",
  "date": "2024-09-15",
  "seasons": [
    { "opens": "2024-09-01", "closes": "2024-11-30", "source": { "url": "...", "date": "2024-07-15", "verbatim": "Montana FWP §12.2.1" } }
  ],
  "tags": {
    "general": { "limit": 1, "source": { ... } },
    "draw": { "deadline": "2024-06-01", "purchaseLink": "https://...", "source": { ... } }
  },
  "methods": {
    "rifle": true,
    "bow": true,
    "crossbow": false,
    "source": { ... }
  },
  "reporting": null,
  "contacts": [
    { "agency": "CPW", "phone": "1-800-244-5613", "url": "...", "source": { ... } }
  ],
  "sources": [
    { "url": "https://fwp.mt.gov/hunt/regulations", "date": "2024-07-15", "title": "Montana FWP Hunting Regulations" }
  ]
}
```

**Key difference:** `reporting` is explicitly `null`, not omitted. All sections are always present in the response structure.

**React rendering code:**
```jsx
return (
  <>
    <SeasonCard data={data.seasons} source={data.seasons?.[0]?.source} />
    <TagCard data={data.tags} source={data.tags?.source} />
    <MethodCard data={data.methods} source={data.methods?.source} />
    <ReportingCard data={data.reporting} />
    <ContactsCard data={data.contacts} />
  </>
);

// ReportingCard handles null gracefully:
function ReportingCard({ data }) {
  if (!data) return <EmptyState message="No reporting required." />;
  return <ReportForm {...data} />;
}
```

**Pros:**
- Response shape is always the same; frontend UI structure never changes
- Null values are explicit: "this section doesn't apply" not "this section is missing"
- Empty state is a rendering concern, not a structural one: all slots render; content varies
- Skeleton loading is trivial: same slot structure, swap real data for `<Skeleton />`
- Deep linking works: `/regulations?#tags` always works because tags slot always exists
- API evolution is safe: adding a new field doesn't break old clients; removing a field requires versioning
- TypeScript types are clean: `{ seasons: Season[], tags: Tags | null, ... }`
- Each section can declare its own source/authority independently

**Cons:**
- Slightly larger JSON payload (all sections always present)
- Clients must handle null checks everywhere (but this is explicit, not hidden)

**Verdict:** This is the professional, production pattern. Used by Stripe (all optional fields present), eCFR (all sections shown regardless of content), and Redfin (all slots always render).

---

## Part 6: Response Shape Implications for React & Next.js 14+

### Skeleton Loading with Shape C

With an explicit envelope, skeleton loading is deterministic:

```jsx
// Define skeleton structure once, reuse everywhere
const REGULATION_SKELETON = {
  seasons: <Skeleton className="h-32" />,
  tags: <Skeleton className="h-48" />,
  methods: <Skeleton className="h-20" />,
  reporting: <Skeleton className="h-16" />,
  contacts: <Skeleton className="h-24" />,
};

function RegulationPanel({ isLoading, data }) {
  const displayData = isLoading ? REGULATION_SKELETON : data;
  return (
    <>
      {displayData.seasons && <SeasonSection data={displayData.seasons} />}
      {displayData.tags && <TagSection data={displayData.tags} />}
      {/* ... */}
    </>
  );
}
```

With Shape A or B, you'd need to hardcode which sections to skeleton; you can't derive it from the response.

### React Server Components & Streaming (Next.js 14+)

Shape C aligns perfectly with streaming:

```jsx
// app/hunt/[id]/page.tsx
async function HuntPanel({ lat, lng, species, date }) {
  return (
    <div className="space-y-4">
      <Suspense fallback={<Skeleton className="h-32" />}>
        <SeasonSection promise={getSeasons(lat, lng, species, date)} />
      </Suspense>

      <Suspense fallback={<Skeleton className="h-48" />}>
        <TagSection promise={getTags(lat, lng, species, date)} />
      </Suspense>

      <Suspense fallback={<Skeleton className="h-16" />}>
        <ReportingSection promise={getReporting(lat, lng, species, date)} />
      </Suspense>
    </div>
  );
}
```

Each section loads independently. If one fetch is slow, others stream first. **This works best when your API already returns the envelope shape**—the UI mirrors the response structure exactly.

With Shape A (flat array), you'd have to reconstruct the envelope in the browser or have each section fetch its own data. Loose coupling at the cost of multiple roundtrips or reconstruction logic.

### Deep Linking

Shape C enables stable section URLs:

```
/map?lat=40.0&lng=-105.2&species=elk&date=2024-09-15#tags
/map?lat=40.0&lng=-105.2&species=elk&date=2024-09-15#reporting
```

The UI can scroll to or highlight the `#tags` section because it knows it will always exist. With Shape A or B (omitted sections), a deep link to a non-existent section is broken.

---

## Part 7: Citation Rendering – Response Shape Impact

### Per-Section Citations (Shape C Best Practice)

Embedding `source` at the section level enables clean citation UI:

```json
{
  "tags": {
    "data": { "general": { "limit": 1 }, "draw": { "deadline": "2024-06-01" } },
    "source": {
      "url": "https://fwp.mt.gov/hunt/regulations",
      "date": "2024-07-15",
      "verbatim": "Montana FWP Regulations § 12.5",
      "confidence": "official"
    }
  }
}
```

**UI rendering:**

```jsx
<div className="space-y-4">
  <TagForm data={data.tags.data} />
  <SourceCard>
    <a href={data.tags.source.url} target="_blank" rel="noreferrer">
      {data.tags.source.verbatim}
    </a>
    <p className="text-xs text-gray-500">Published {format(data.tags.source.date)}</p>
  </SourceCard>
</div>
```

This guarantees that each section's authority is visible and traceable. Users never see a regulation claim without knowing where it came from.

### Per-Record Citations (Flat Array)

Shape A requires attaching source to every record:

```json
[
  { "type": "tag", "limit": 1, "source": { "url": "...", "date": "...", "verbatim": "..." } },
  { "type": "tag", "limit": 1, "draw": true, "source": { "url": "...", "date": "...", "verbatim": "..." } }
]
```

This works, but it's repetitive if multiple records cite the same source. Shape C's per-section structure avoids repetition.

---

## Part 8: Resilience to Shape Evolution

### Shape A: Adding a new regulation type

Current response: array of `[season, tag, method]` records.

New requirement: include `safety_requirements` regulations.

**Change:** Add `{ type: 'safety_requirement', ... }` to array.

**Frontend impact:** Any component that hardcodes `['season', 'tag', 'method']` breaks. The component doesn't know about safety requirements. You must update every grouping filter.

---

### Shape B: Adding a new section

Current response: `{ seasons, tags, methods, reporting }`

New requirement: include `restrictions` (e.g., "no hunting within 1 mile of school")

**Change:** Add `restrictions` field to envelope.

**Frontend impact:** The sidebar still renders correctly (because of `{data.restrictions && <RestrictionsCard ... />}`), but now one component knows about a section the API doesn't return. Unused slot. Worse: if a developer copies the sidebar code to a different app where `restrictions` *is* returned, they forget to render it.

---

### Shape C: Adding a new section

Current response: `{ seasons, tags, methods, reporting: null, contacts, sources }`

New requirement: include `restrictions`

**Change:** Add `restrictions: null` or `restrictions: [...]` to envelope.

**Frontend impact:** Zero. The sidebar code already renders `<RestrictionsCard data={data.restrictions} />`. If restrictions is null, it shows empty state. If restrictions has data, it shows the data. No conditional logic changes.

**TypeScript impact:**
```typescript
interface Regulations {
  seasons: Season[];
  tags: Tags | null;
  methods: Methods;
  reporting: Reporting | null;
  restrictions: Restriction[] | null; // New
  contacts: Contact[];
  sources: Source[];
}
```

Type-safe. Clients that haven't upgraded to the new type still work (restrictions is optional in older versions). New clients get the field.

**Verdict:** Shape C is most resilient to evolution. The structure is explicit and stable; new fields don't require frontend changes.

---

## Synthesis & Recommendation

### Dominant Patterns (Regulatory Data UI)

1. **Fixed envelope with explicit slots** – Every surveyed legal/regulatory UI (Westlaw, eCFR, Federal Register, Stripe) uses this.
2. **Null/empty affordances, not missing slots** – Absence is explicit, not implicit.
3. **Citations nested in sections** – Authority preservation is architectural, not an afterthought.
4. **Consistent structure regardless of coverage** – Empty states are UI concern, not structural.
5. **Single source of truth for section structure** – Response shape and UI mirror each other exactly.

### The Competition

| **Aspect** | **Shape A (Flat)** | **Shape B (Omitted)** | **Shape C (Explicit Null)** |
|---|---|---|---|
| **Rendering complexity** | High (filter, group, detect) | Medium (conditional keys) | Low (render all slots) |
| **Empty state detection** | `length > 0` checks scattered | `data.section && ...` scattered | Implicit; slot renders null affordance |
| **Skeleton loading** | Hard (don't know structure) | Medium (hardcode sections) | Easy (same structure, swap content) |
| **Deep linking** | Breaks for missing sections | Breaks for missing sections | Always works |
| **Type safety** | Union of record types | Optional fields | Required + null fields |
| **Evolution safety** | Breaks on type additions | Breaks on grouping changes | Safe (add fields, render existing) |
| **Citation clarity** | Per-record (repetitive) | Unclear (omitted source) | Per-section (clear, nested) |
| **Matches surveyed UIs** | No | Partially | Yes (Stripe, eCFR, FR, Redfin) |

### The Call

**Use Shape C: Structured envelope with explicit null/empty sections.**

This is not a guess. Every production UI rendering structured regulatory/legal data with citations—Stripe, eCFR, Federal Register, Westlaw, Redfin, Zillow—uses this pattern. It minimizes conditional logic, supports skeleton loading, enables deep linking, and scales cleanly as regulations evolve.

Your response shape should be:

```typescript
interface Regulations {
  point: { lat: number; lng: number };
  species: string;
  date: string;
  
  // Always present; content may be null
  seasonWindows: SeasonWindow[] | null;
  tags: {
    general?: Tag;
    draw?: Tag;
    source: Source;
  } | null;
  methodsOfTake: {
    allowed: string[];
    prohibited?: string[];
    source: Source;
  } | null;
  reportingRequirements: ReportingRequirement[] | null;
  agencies: Agency[]; // May be empty array, not null
  
  // Metadata
  sources: Source[]; // All cited sources, normalized
}

interface Source {
  url: string;
  date: string;
  verbatim: string; // The actual rule text or cite
  confidence: "official" | "inferred" | "incomplete";
}
```

Each section that can be missing is `null`. Each section that always has data is an array or object. The frontend renders the structure once; slots render either content or an empty-state affordance.

---

## References & Sources

- [Stripe API Reference Documentation](https://docs.stripe.com/api) – Three-column layout, consistent envelope structure
- [eCFR (Electronic Code of Federal Regulations)](https://www.ecfr.gov/) – Section-based hierarchy, source metadata in sidebar
- [Federal Register Document Features & Sidebar](https://www.federalregister.gov/reader-aids/using-federalregister-gov/document-features-sidebar) – Key Information sidebar with citations
- [Nielsen Norman Group: Empty State Interface Design](https://www.nngroup.com/articles/empty-state-interface-design/) – Best practices for absence/unknown states
- [PatternFly Empty State Design Guidelines](https://www.patternfly.org/components/empty-state/design-guidelines/) – Card-based empty state patterns
- [React Suspense & Streaming (Next.js 14+)](https://nextjs.org/docs/app/building-your-application/routing/loading-ui-and-streaming) – Structural consistency for RSC boundaries
- [API Design: Optional vs. Nullable Fields](https://www.apimatic.io/blog/2021/09/using-optional-and-nullable-properties-in-api-requests) – Semantics of null in structured responses
- [OnX Hunt](https://www.onxmaps.com/hunt/app) – Hunting map app with regulatory awareness
- [HuntWise Hunting App](https://huntwise.com/) – Personalized hunt context + regulations drawer
- [Casetext Legal Research](https://casetext.com/) – AI case summaries with SmartCite inline citations
- [Redfin Property Details](https://www.redfin.com/) – Real estate panel structure (property facts, market insights)
- [Zillow Listing Pages](https://www.zillow.com/) – Property details with information hierarchy
- [Gov.uk Design System Components](https://design-system.service.gov.uk/components/) – Government UX patterns for structured information
- [Sidenotes in Web Design (Gwern.net)](https://gwern.net/sidenote) – Margin-based citation rendering for dense regulatory text

