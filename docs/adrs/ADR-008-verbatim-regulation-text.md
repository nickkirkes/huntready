# ADR-008: Verbatim Regulation Text

**Date:** 2026-04
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** schema, product

---

## Context

HuntReady's authority commitment ([ADR-001](ADR-001-authority-preserved.md)) says the product routes to agency sources rather than interpreting them. That commitment has to land at a specific layer or it dissolves. The layer where it lands is the text itself — the actual regulation prose in a response — not just the citation that accompanies it.

Regulation language carries statutory precision that paraphrase destroys. Montana's landowner preference rule reads "a landowner must own at least 160 acres of land within the hunting district applied for" for deer and antelope, and "at least 640 contiguous acres of land used by elk as documented by FWP" for elk. That delta is not a wording difference; it is a different rule, and a paraphrase that collapsed them would produce a product that is wrong about who qualifies.

## Decision

Every regulation reference carries a `verbatim_rule` string containing the exact published text from the authoritative source; records without verbatim text fail ingestion validation and do not enter the corpus.

## Reasoning

Ingestion is structured extraction plus verbatim preservation, not summarization. The pipeline may identify that a block of text describes a season window with specific dates and a weapon type, extract those into structured columns, and simultaneously store the original prose in `verbatim_rule`. The structured fields let the server answer questions; the verbatim string lets the user verify the answer against the source's actual words.

Carrying verbatim text at the schema layer turns the authority commitment into a hard constraint. An ingestion run that cannot produce `verbatim_rule` produces no record. A missing-verbatim bug becomes a loud validation failure, not a subtle UI omission — enforced by the thing hardest to circumvent, the database schema.

The response envelope ([ADR-011](ADR-011-shape-c-response-envelope.md)) surfaces `verbatim_rule` on every resolved section. Agentic clients can quote it back to users; the web companion renders it in a disclosure on each panel, visible on demand, with the source link one click away. The user gets two independent views of the same rule — structured summary and original prose — and can reconcile any disagreement against the authority.

Verbatim text also makes `confidence` meaningful. A `medium`-confidence extraction is one where structured fields were inferred from prose, but the prose itself is stored verbatim; the user can judge the inference. Without verbatim text, `confidence` would degrade to a claim without evidence.

## Consequences

### Positive

- The authority commitment is enforced at the layer hardest to violate — the schema itself.
- `verbatim_rule` gives `confidence` something to point at; a medium-confidence record has the original prose for the user to judge against.
- Corrections are handled cleanly: a corrected record's new `verbatim_rule` is the corrected text, with the `supersedes` pointer carrying the history.

### Negative

- Verbatim regulation prose is long, legalistic, and sometimes internally inconsistent. UI and agent responses carrying it are harder to make pleasant than paraphrased equivalents would be.
- Some sources encode rules as scanned images, tables too unstructured for reliable extraction, or prose too ambiguous to isolate a verbatim string that corresponds to a structured claim. Such records cannot be ingested under this ADR, shrinking addressable coverage.
- Storage cost rises nontrivially — every record carries structured fields and full source prose — though at V1 scale this is not binding.

### Neutral

- This ADR closes off product directions that would otherwise be open: plain-language rewrites, AI-authored summaries, and any feature that synthesizes text beyond composition of verbatim pieces. These closures are coherent with [ADR-001](ADR-001-authority-preserved.md).

## Links

- [ADR-001](ADR-001-authority-preserved.md) — The authority commitment this ADR implements at the schema layer.
- [ADR-006](ADR-006-schema-versioned-from-day-one.md) — Verbatim text is part of the schema contract that evolves under versioning.
- [ADR-010](ADR-010-decomposed-entity-model.md) — The entity model in which `verbatim_rule` is carried on every structural unit.
- [ADR-011](ADR-011-shape-c-response-envelope.md) — The response shape that surfaces `verbatim_rule` to consumers.
- [`docs/architecture.md`](../architecture.md) — "Verbatim text, confidence, and corrections."
