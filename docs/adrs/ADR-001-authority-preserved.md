# ADR-001: Authority Preserved, Not Replaced

**Date:** 2026-04
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** product

---

## Context

HuntReady delivers regulation content to hunters who make legally consequential decisions based on it. A paraphrased season date, a simplified tag rule, or a missing citation can move a hunter from compliant to poaching without their knowing. State wildlife agencies are the authoritative source for hunting regulation, and any product that intermediates them takes on a share of the correctness burden they already carry.

The market gap HuntReady addresses is not that regulation text is unavailable — it is that the text is fragmented across PDFs, agency portals, unit maps, and correction notices with no entry point indexed by what a hunter actually asks (location, species, date). The gap is routing and assembly, not interpretation.

## Decision

HuntReady routes hunters to authoritative state-agency sources rather than replacing them; regulation text is carried verbatim with source citations preserved on every record and every response.

## Reasoning

The product discipline and the liability discipline point to the same architecture. If HuntReady paraphrases a regulation and the paraphrase is wrong, the hunter who relied on it has been harmed and HuntReady has manufactured the harm. If HuntReady routes the hunter to the agency's own text with the section reference and publication date, the product has added value without inserting itself between the hunter and the source of truth.

The commitment is enforced in three places. At the schema layer, every regulation record requires a source citation — URL, agency, publication date — and records without citations fail validation before they enter the corpus. At the response layer, every MCP tool response includes source links and publication dates, and the web companion renders them prominently on every panel. At the text layer, regulation prose is carried verbatim from the source; ingestion extracts and structures but does not summarize.

The corollary is that a regulation which cannot be rendered faithfully is not rendered at all. A partial or paraphrased regulation is worse than a missing one because it creates the appearance of authority the product does not hold.

## Consequences

### Positive

- Legal posture is defensible: HuntReady is a routing and assembly layer, not an interpretation layer.
- Users can verify every answer in one click, which makes the product trustworthy under scrutiny.
- Source citations are a first-class schema constraint, which forces ingestion quality upstream rather than papering over it downstream.

### Negative

- The product cannot offer plain-language summaries of dense regulations — the single most-requested feature in any regulation product is permanently off the table under this ADR.
- Verbatim text is long and legalistic; the UI has to carry the burden that paraphrase would have carried.
- Regulations that exist only as scanned images or as prose without extractable structure may be impossible to ingest at acceptable quality, shrinking addressable coverage.

### Neutral

- This ADR commits the product to a permanent boundary with legal-interpretation products and with hunter-education products. The boundary is not reversible without rewriting the product's identity.

## Links

- [`docs/context.md`](../context.md) — "Authority boundaries" establishes this commitment in the product frame.
- [ADR-002](ADR-002-mcp-canonical-interface.md) — The canonical interface exists to route, not to interpret.
- [ADR-008](ADR-008-verbatim-regulation-text.md) — Enforces the text-layer commitment at the schema level.
