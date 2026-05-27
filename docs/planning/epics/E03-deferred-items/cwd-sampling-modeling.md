# CWD Sampling Modeling (Q18)

This file tracks the deferred ADR-grade question of whether `reporting_obligation` rows should model per-zone CWD sampling rules in V1. Surfaced during S03.9 planning (2026-05-19) by the source-audit probe; deferred per Q18 to M2 when a second CWD-state (Colorado) lands.

Per the S03.9 disposition: ship 0 CWD-sampling `reporting_obligation` rows; the verbatim text lives in `regulation_record.additional_rules` after S03.6 ingestion. Revisit when M2 brings Colorado's CWD framework.

---

## The architectural question

Should CWD sampling be modeled as:

- (a) `reporting_obligation` rows keyed by ZONE, joined to regulation_records via `geometry-overlays.json` CWD-zone-overlap lookup, OR
- (b) `reporting_obligation` rows keyed by LICENSE_TAG (since the sampling mandate is bound to the LICENSE in the source), OR
- (c) Left in `regulation_record.additional_rules` (current S03.6 state — V1 disposition)

## V1 evidence

The 10-day-sampling sentence appears **5 times across 4 HDs** as per-license `extras` cells in `ingestion/states/montana/extracted/dea-2026.json`:

| HD | License | Zone | In overlay fixture? |
|----|---------|------|---------------------|
| 100 | Deer B License: 199-20 | Libby | Yes |
| 103 | Deer B License: 199-20 | Libby | Yes |
| 103 | Deer Permit: 103-50 (North Fisher Portion) | (no zone in text) | **No** |
| 104 | Deer B License: 199-20 | Libby | Yes |
| 170 | Deer B License: 170-20 | Kalispell | Yes |

The `103-50` case is the canonical edge case: a sampling mandate keyed off harvested-animal-license-type, not strictly geographic CWD-zone-overlap. The zone-keyed option (a) would miss it.

## What V1 ships

S03.6 has already captured all 5 verbatim occurrences in `regulation_record.additional_rules`. S03.9 ships **0** CWD-sampling `reporting_obligation` rows. Clients querying "what regulations apply to HD 100 (or 103-50)?" already get the sampling text via the `additional_rules` field.

## What moves this to a decision

- Colorado V2 lands: does CO's CWD framework follow zone-keyed or license-keyed conventions? Both states' patterns inform whether a typed `kind="cwd_sample"` reporting_obligation is worth the schema complexity.
- M2 client requirement: does any consumer query need to enumerate "all CWD sampling rules" as a typed reporting_obligation, or is `regulation_record.additional_rules` containing the sentence sufficient?
- Q18 in `docs/open-questions.md` is the canonical landing place when this decision is made.

## Companion entries

- **Open question:** `docs/open-questions.md` § Q18
- **Working note:** S03.9.md (deleted at m1 tag per ADR-017 §6); the Probe 2 CWD sampling analysis is summarized in this file's body above.
