# ADR-017: Confidence Calibration and Parent-Inheritance Rule

**Date:** 2026-05
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** ingestion, schema

---

## Context

Q11 (open since M0): how does the project assign confidence to ingested data, and how do consumers interpret it?

Schema reality (as set up by E01):

- `RegulationRecord.confidence: Literal["high", "medium", "low"]`
- `VerbatimRule.confidence: Literal["high", "medium", "low"]` (where VerbatimRule appears in `RegulationRecord.additional_rules` jsonb)
- No other entity has a confidence column. `SeasonDefinition`, `LicenseTag`, `DrawSpec`, `ReportingObligation`, `Geometry`, and `JurisdictionBinding` carry none.

E03's regulation-text extraction surfaced the question: how do confidence values flow from a per-extraction-row signal to the database, given that most entities have no field for it?

Three options:

- (a) Inherit confidence from parent `regulation_record` for child entities; no schema change
- (b) Add `confidence` to all six entity tables (E03-scale schema migration)
- (c) Compute confidence on read in the MCP server; no storage at all

## Decision

**Option (a) with explicit caveats.** Confidence stays on `regulation_record` and `VerbatimRule`. Child entities inherit at query time. Spatial entities (`geometry`, `jurisdiction_binding`) are explicitly outside the framework and use their own provenance signals.

## Reasoning

### 1. Inherited confidence (regulation-text entities)

`season_definition`, `license_tag`, `draw_spec`, `reporting_obligation` rows inherit confidence from their parent `regulation_record`. The schema does NOT store it on these tables. The inheritance is **derivable** at query time by joining through `regulation_record`. Whether and how a future MCP server response composer (M3) surfaces inherited confidence on resolved-section response shapes is M3's call — this ADR guarantees the inheritance is well-defined and computable, not how it gets rendered.

### 2. No inherited confidence (spatial entities)

`geometry` and `jurisdiction_binding` rows DO NOT inherit confidence from any source. They are a different epistemological category — geometric/spatial data sourced from FWP ArcGIS layers (`geometry`) or computed from spatial overlap (`jurisdiction_binding`). The three-tier confidence framework was designed around regulation-text extraction signals (table-cell vs prose vs heuristic); those signals don't translate to "how reliable is this polygon."

Geometry and jurisdiction_binding carry **different provenance shapes** than regulation-text rows: `geometry` carries a source-layer reference (the FWP ArcGIS layer that produced it, per ADR-014's `gis_layer` document_type); `jurisdiction_binding` carries an area-overlap percentage (per ADR-016's three-band discriminator). Consumers asking "how confident is this binding?" should consult the appropriate provenance per entity type. If that proves operationally insufficient in a future epic, promote spatial-confidence via a future ADR amending ADR-016 — do not silently extend ADR-017.

### 3. Per-VerbatimRule confidence

`RegulationRecord.additional_rules[*].confidence` is its own value, calibrated per the same three-tier framework as the parent record. A high-confidence regulation_record can carry medium-confidence additional_rules entries (e.g., the structured fields are clean but a NOTE: paragraph required prose interpretation).

### 4. Three-tier framework

- **`high`:** extracted from a structured table cell, regex-validated against expected pattern, no manual interpretation. Signals: source format is structured (table); extraction is deterministic (regex/parser); transformation is one-step (cell → field).
- **`medium`:** extracted from prose with a deterministic heading anchor; structure is consistent across rows but not table-grid-precise. Signals: source format is prose with structural cues (heading + repeated pattern); extraction requires interpretation (e.g., date-range parsing from prose); transformation is up to two steps (prose → parsed field, OR table cell + correction merge).
- **`low`:** extracted via heuristic; requires manual review or LLM-assisted interpretation. Signals: source format is unstructured prose OR fuzzy match (heading-to-id matching with multiple plausible candidates); extraction requires multi-step inference; OR the row was hand-corrected post-extraction.

**Correction-touched rows demote one tier.** When a correction PDF (per ADR-014's `correction` document_type) modifies a row, the row's confidence drops one tier from where it would otherwise sit (`high` → `medium`, `medium` → `low`). The demotion is automatic; it captures the reality that a correction event introduces a transformation step (merge logic) and a temporal-validity ambiguity (the original was wrong; the correction may itself be partially wrong) that the unmodified-source signals don't reflect. A `low`-tier row touched by a correction stays at `low`.

**Demotion applies at the per-row level.** The aggregation rule in section 5 then operates on per-row values that already incorporate any correction-touched demotions. (I.e., a regulation_record's MIN-aggregation reads each contributing row's *post-demotion* confidence, not the pre-demotion source-signal confidence.)

### 5. Aggregation rule

When an extraction artifact has per-row confidence values that feed a single regulation_record (multiple license rows from one HD, multiple closure-prose rows from one BMU, etc.), the regulation_record's confidence is the **MIN** across the contributing values. Most-uncertain wins. The rule reflects the user-facing question: "should I trust this regulation?" — answer is "no more than its weakest part."

**MIN is deliberate.** A consequence: a single low-confidence signal (one heuristically-extracted closure-prose line, one fuzzy-matched legal description) demotes the entire `regulation_record` to `low`. This is the correct user-facing semantic — a regulation is only as trustworthy as its weakest extracted component, and surfacing that to the consumer is preferable to silently averaging it away. Operators who find this aggressive should investigate the low-confidence component (and possibly raise its confidence by improving extraction) rather than soften the aggregation.

### 6. Calibration findings artifacts (E03 working notes)

During E03, each ingestion story emits a `docs/planning/epics/E03-confidence-findings/<story>.md` capturing every signal used and every edge case encountered. These artifacts feed S03.11's audit and the final form of this ADR.

**They are working notes for ADR-017 drafting; they do not survive past M1 close.** **Deletion mechanism: manual `git rm -r docs/planning/epics/E03-confidence-findings/` as part of the same commit that pushes the `m1` tag (the final S03.12 commit).** The directory is named in `.gitignore` for the post-M1 period to prevent accidental re-creation. The ADR is the durable record.

### 7. Q12 deferral path

If Montana-only signal proves insufficient for any aspect of this calibration during E03 implementation, the relevant section of this ADR is marked "deferred to M2" and the question stays open in `open-questions.md`. Per PRD 001 R4: do not block E03 on Q11's resolution if signal is insufficient.

The deferral test is **OR-ed** (any one condition triggers deferral; not all three required):

- Any documented edge case maps to >1 tier without contradiction, **OR**
- Any tier has 0 rows in Montana data, **OR**
- Audit pass-rate <80% against this framework

If any of the three triggers, the framework is deferred — wholly or partially — and the ADR's affected section moves to "deferred to M2" with a documented reason.

## Alternatives considered

- **(b) Add `confidence` to all six entity tables.** Rejected for V1: opens per-cell confidence questions (which of a row's fields drives the row's confidence?) without a clear consumer need. The schema migration is also non-trivial (six tables × three-place sync). Future ADR can revisit when M3 (MCP server) or M4 (web composer) surfaces a real use case requiring per-entity confidence.
- **(c) Compute confidence on read in MCP server.** Rejected: requires consumers to re-derive a value the producer already knows; harder to audit; couples MCP server to extraction logic, which violates ADR-003 (ingestion upstream and offline).

## Consequences

- ADR-017 is the resolution for Q11. Q11 entry in `open-questions.md` moves to "Recently resolved" with link to this ADR.
- Spatial confidence (geometry, jurisdiction_binding) is explicitly out of this framework. Out-of-scope question stays open for a future epic.
- The per-story working-notes artifacts are deleted at the `m1` tag commit. Only the durable ADR + the audit trail on each ingested row's `source` jsonb is preserved past M1 close.
- E03 ingestion stories (S03.6 onward) implement the inheritance rule by computing the `regulation_record.confidence` value at ingestion time and not writing per-child-entity confidence anywhere.
- **Confidence values are authoritative-at-time-of-ingestion.** A future framework amendment (e.g., reordered tier definitions, new edge-case rules, threshold changes) does NOT implicitly re-classify existing rows. Re-classification requires a deliberate re-ingestion run that overwrites rows with the new framework's values. `RegulationRecord.schema_version` (verified present at `supabase/migrations/20260425000000_initial_schema.sql:41`) and `SourceCitation.publication_date` together identify which framework was applied to which row — `schema_version=2` rows carry ADR-017's V1 framework; a later schema_version increment would signal a framework change.
