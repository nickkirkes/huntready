# E03 Epic Review

**Epic:** [E03 — Montana Regulation Text Ingestion](E03-regulation-text-ingestion.md)
**Review date:** 2026-05-03
**Reviewer:** Roughly epic-reviewer (model: opus)
**Verdict:** **NEEDS REVISION**

---

## Summary

Multiple correctness-affecting issues in the cross-species filter, one undefined-by-construction case in the date-arbitration logic, an order-of-operations bug between S03.6 and S03.7 around `license_tag.draw_spec_key`, and at least three load-bearing ACs missing from the AC checklists. None are unfixable; most are 1-3 line clarifications. The epic is structurally strong (E02 patterns mirrored cleanly, ADR-017/018 already accepted) but the cross-cutting "operational definition of flag" interacts with several stories in ways that need tightening before implementation.

---

## Critical findings (must address before implementation)

### C1. S03.10 cross-species filter is structurally wrong for whitetail (technical accuracy / risks)

**Lines 776–778** state:

> For `species_group ∈ {elk, mule_deer, whitetail}` with `jurisdiction_code='MT-HD-deer-elk-lion-N'`, accept children starting with `MT-HD-deer-elk-lion-` (which captures all three deer/elk/whitetail portions since they share that namespace from layer #11)…

This claim is contradicted by the overlay fixture's actual contents. The fixture inspected shows children with namespaces like `MT-HD-elk-215-portion-elPt21-geom` and `MT-HD-mule-deer-312-portion-...-geom` — i.e., **portions are namespaced per-species (`elk`, `mule-deer`), NOT all under `deer-elk-lion-`.** The "all three share the namespace from layer #11" assumption is incorrect for portions. Layers #11/#12/#13/#14 are species-specific portion layers per E02, and the IDs produced reflect that.

**Concrete consequence:** the filter rule as written ("accept children starting with `MT-HD-deer-elk-lion-`") will reject ALL portion bindings for elk/mule_deer/whitetail regulation_records, producing zero portion-role bindings instead of the intended ~50 per-species. M1 UAT criterion #3 ("PostGIS `ST_Contains` query… returns HD 262 + any overlay BMU/CWD/Portion (same-species)") will fail.

**Proposed fix:** rewrite the filter rule for the deer/elk/whitetail family to accept children whose namespace matches the regulation_record's `species_group`:
- `species_group='elk'` → accept children starting with `MT-HD-elk-` (portions) OR `MT-HD-deer-elk-lion-N-geom` (the self-row primary_unit) OR species-agnostic kinds.
- `species_group='mule_deer'` → accept `MT-HD-mule-deer-`, plus the self-row, plus species-agnostic.
- `species_group='whitetail'` → there is **no `MT-HD-whitetail-` portion layer** in E02 (verify against the fixture; only elk and mule_deer portion layers were ingested per the CLAUDE.md summary "55 portions (#4, #12, #13, #14)" and the species in those layer IDs). If whitetail has no portion layer, the filter must explicitly handle that — bind only the self-row + species-agnostic, OR document that whitetail inherits mule_deer's portions, OR mark this as a gap and flag-and-defer.

This finding alone requires a re-walk of S03.10 against the actual fixture before the AC list is final. The unit test ACs ("explicit unit tests for each species pair") need concrete counts derived from the fixture, not generic round-trip tests.

### C2. S03.4 date-arbitration has no defined behavior when publication dates collide (technical accuracy / risks)

**Lines 360–366** define the merge as "MAX `source_publication_date` wins." Two undefined cases:

1. **Two corrections with the same date amend the same cell.** The MAX is non-unique. The epic gives no tiebreaker (e.g., later-fetched-at wins, alphabetical citation_id, raise an error).
2. **Correction PDF has a missing or unparseable `publication_date`.** `sources.yaml` allows `publication_date: ISO date` but doesn't say what happens if a real correction surfaces with no date stamp. MAX over `{date, None}` is implementation-defined (Python raises `TypeError`; pandas treats NaT as smaller; the load script's behavior is unspecified).

**Proposed fix:** add an AC to S03.4: "when two correction operations target the same cell with equal `publication_date`, the loader raises `CorrectionConflictError` with both source_ids in the message; an unparseable/missing `publication_date` is a fail-loud condition (raises during `sources.yaml` load, never reaches the merge stage)."

The 2026-03-18 correction is the only one in V1 so this never fires in M1 — but if M2 surfaces a second correction for the same booklet, the implementation will silently order-of-iteration its way to one or the other. Make the contract explicit now.

### C3. S03.6 AC for "geometry-text enrichment from S03.5" creates an order-of-operations cycle with S03.5's own dependency declaration (dependencies / technical accuracy)

**S03.5 line 449** declares: "Depends on: S03.1, S03.2; S03.0 (the `geometry.legal_description` column must exist); **consumes E02's `geometry` table for the matching pass.**"

**S03.6 line 525** says: "This story writes `geometry.legal_description`… for matched geometry rows."

**S03.5 AC line 454** says: "Every prose description matched to an existing `geometry_id`…"

The matching pass in S03.5 only needs the geometry IDs, which exist after E02 (and S03.0 adds `MT-STATEWIDE-geom`). That's fine. But S03.5's AC says it writes `geometry_id` into the extraction artifact, while S03.6 writes that mapping into the `geometry.legal_description` column. **However, S03.6's "Depends on" line includes "S03.5 (Legal Descriptions for geometry-text enrichment)"** — correct.

The real issue: **S03.5 writes a JSON artifact only; S03.6 writes the column.** But S03.6's AC list at line 541 says "Geometry-text enrichment from S03.5 written to `geometry.legal_description` for matched rows; no `verbatim_rule` overload" — that's correct. The conflict is more subtle: nothing in the epic says S03.5 itself must NOT write to `geometry.legal_description`, only that S03.6 will. Two implementers reading the spec independently could both write the column. Add a one-liner to S03.5: "S03.5 produces only the JSON artifact; the database write to `geometry.legal_description` is S03.6's responsibility (avoids dual-writer ambiguity)."

This is a low-effort fix but the kind of thing that surfaces as a re-work after one PR lands.

### C4. S03.8 depends on S03.7 for `license_tag.draw_spec_key`, but S03.7's AC list never says S03.7 writes it (dependencies / AC quality)

**S03.8 line 669** declares: "Depends on: S03.7 (license_tag rows with `draw_spec_key` populated)."

**S03.7 line 575** mentions in passing: "create a `license_tag` row with `license_code`, `kind`, `weapon_types`, `residency`, `quota`, `quota_range`… `verbatim_rule`."

`draw_spec_key` is not in that list. It's also not in S03.7's AC checklist (lines 612–626). But S03.8 AC line 676 then asserts: "`license_tag.draw_spec_key` jsonb correctly references the `draw_spec` composite PK for every draw-eligible license_tag."

**Order-of-operations problem:** if S03.7 doesn't populate `draw_spec_key` when writing license_tag, then S03.8 must `UPDATE license_tag SET draw_spec_key = ?` after writing draw_spec rows. That's fine architecturally (chicken-and-egg between license_tag and draw_spec is a real schema reality), but it must be **stated explicitly somewhere in the epic.**

**Proposed fix:** in S03.7 context, add: "S03.7 leaves `license_tag.draw_spec_key=NULL` for all license_tag rows. S03.8 backfills `draw_spec_key` after writing draw_spec rows, via UPDATE. The schema permits NULL because draw_spec_key is a soft FK (per ADR-012), so this isn't a constraint violation between the two writes." Update S03.8's AC to assert: "S03.8 UPDATEs license_tag.draw_spec_key for limited-draw license_tags after writing the corresponding draw_spec rows; the load script is idempotent against re-runs."

Alternative: have S03.7 write license_tag without draw_spec_key, and have S03.8 write both the draw_spec AND the UPDATE in one transaction. Either works — the fix is to be explicit.

### C5. S03.7 "MIN aggregation" AC mismatch between S03.6 and S03.7 (best practices / AC quality)

**S03.6 line 537** asserts: "every row has… populated `confidence` per ADR-017's MIN aggregation."

**S03.6 line 519** says: "For each regulation_record, `confidence = MIN` over all extraction-row confidences that fed it."

But ADR-017 §5 (lines 58-62) defines MIN as the *most-uncertain* tier wins. The natural Python implementation is `min(["high", "medium", "low"])`, which lexicographically returns `"high"` (h < l < m). Implementer must use a tier-ranked MIN, not string-MIN. The epic doesn't call this out.

**Proposed fix:** S03.6 should reference an explicit helper from S03.2's confidence framework (e.g., `ConfidenceTier.min_tier(rows: Iterable[ConfidenceTier]) -> ConfidenceTier`) and the AC should test it against the trap case (`min(["high", "low"])` returns `"low"`, not `"high"`).

S03.2's AC at line 222 ("Confidence framework helpers reference ADR-017 (signal definitions, MIN aggregation, correction-touched demote-one-tier rule)") is too vague to lock this in. Add an AC: "MIN aggregation helper unit-tested with `('high', 'low') -> 'low'` and `('medium', 'medium') -> 'medium'` to lock in tier-rank semantics, not lexicographic."

This is a known Python pitfall. Worth one explicit test.

---

## Important findings (should address)

### I1. S03.10 deterministic ID format is verbose AND has a real collision risk

**Line 790:** `f"{state}-{jurisdiction_code}-{species_group}-{license_year}-binding-{geometry_id}-{role}"`

A concrete example: regulation_record `(US-MT, MT-HD-deer-elk-lion-262, elk, 2026)` binding to child `MT-HD-elk-215-portion-elPt21-geom` with role `portion`:

```
US-MT-MT-HD-deer-elk-lion-262-elk-2026-binding-MT-HD-elk-215-portion-elPt21-geom-portion
```

Length ~85 chars. Postgres `text` columns have no length cap, so length isn't a hard problem. But:

- `state` is redundant with the `state` prefix in `jurisdiction_code` (every Montana row starts with `MT-`).
- `license_year` is necessary (HD definitions can change between years).
- `species_group` IS necessary (same jurisdiction_code can bind for multiple species at different roles).
- `geometry_id` already encodes a kind prefix and a hierarchy.
- `role` is necessary (same reg_record + same geometry can have multiple roles in principle, e.g., primary_unit and other_overlay).

The verbose format is fine for stability. The bigger issue: **the format embeds `geometry_id` which can contain hyphens, and `jurisdiction_code` which can contain hyphens, and joins them with hyphens.** ID parsing is therefore not round-trippable. That's not an immediate bug but it precludes future deterministic-decoding code without ambiguity.

**Proposed fix:** lower priority. Either accept the format as opaque-but-deterministic and add an AC ("the binding `id` MUST NOT be parsed by downstream code; only used as a stable upsert key") or switch to a hash (`sha256(canonical_json)[:16]` of the constituent fields) for readability. The verbose format wins on debuggability when grep-ing logs, so probably keep it — but add the "do not parse" guard in code comment + AC.

### I2. S03.5 "actionable threshold" for unmatched headings is undefined (risks / AC quality)

**Line 436** says: "Mismatches… are flagged in the output's `unmatched` and `unlinked` arrays for human review — do not silently drop or invent."

**AC line 458:** "`unmatched` array flagged via the operational definition (WARN log + working-note entry)."

But there's no failure threshold. If 3 of 350 headings unmatch, that's a normal operational result. If 200 of 350 unmatch, the extraction is broken and the load shouldn't proceed. The AC just says "flag it" — not "fail loud above N% unmatched."

**Proposed fix:** add a threshold. Suggested: "If unmatched_count / (matched_count + unmatched_count) > 0.10 (10%), `extract_legal_descriptions.py` exits non-zero with a clear error message; the operator must investigate the matching rule before proceeding." 10% is the suggested first cut; PM may pick differently. But the absence of any threshold means a regressed PDF parser (e.g., FWP's 2027 update changes heading format) could silently produce a 90%-empty extraction and look "successful."

Same critique applies to S03.4's `extracted/black-bear-2026-base.json` — if pdfplumber regresses and extracts 5 of 35 BMU rows, the load proceeds with massively incomplete data. Add: "if extracted BMU count < 30 (out of expected 35), the script fails loud" or similar.

### I3. S03.10 no-hunt-zone "nearby" rule can produce zero matches with no fallback (risks)

**Lines 800–803** define "nearby" as `ST_Touches OR ST_DWithin(centroid, 5000m)`. The epic claims "Adds ~30-100 jurisdiction_binding rows total." But what if a no-hunt zone (e.g., Yellowstone NP) has no neighboring HD within 5km of its centroid (Yellowstone's centroid is deep in the park, ~30km from any boundary)?

**Concrete failure mode:** if a zone has zero matches under both predicates, it lands in the database as a `geometry` row with no `jurisdiction_binding` rows pointing to it. From the consumer's perspective, the zone is invisible to spatial regulation queries — the same thing as if E02 had silently dropped it from the overlay fixture.

**Proposed fix:** add an AC: "if any of the 3 EXPECTED_RA_ORPHAN_IDS produces zero binding rows under the nearby-rule, S03.10 fails loud and surfaces the zone for PM review (potentially escalate to Option B/C per the spec)." The current spec says "If during implementation this proves clumsy or surfaces edge cases, escalate to PM" — make that an explicit fail-loud condition, not a soft "investigate."

Yellowstone NP is the most-likely candidate for this exact failure: most of the park is interior; the park's centroid is far from any HD boundary. Worth pre-checking before S03.10 lands.

### I4. S03.11 stratified audit math is undefined when edge-case count exceeds 10 (overengineering / AC quality)

**Lines 853–855:** "≥5 rows per documented edge case + random fill to 50 total."

If there are 6 documented edge cases, that's 30 stratified + 20 random = 50.
If there are 12 documented edge cases, that's 60 stratified — already over the 50 cap, with zero random.
If there are 20, that's 100 stratified.

The AC has no scaling rule. ADR-017 §6 doesn't specify either. The natural reading is "stratified takes priority; random fills up to 50 only if there's room" — but the AC doesn't say that.

**Proposed fix:** rewrite the AC as: "≥5 rows per documented edge case (no upper bound on total stratified samples); random fill brings the audit to **max(50, stratified_count)** rows total. If stratified count alone exceeds 50, that's the audit — random fill is skipped." Or pick a different rule, but pick one.

This affects whether S03.11 can be completed in one session vs. a long-running audit; it also affects whether the 80% pass-rate threshold is statistically meaningful (50 samples with binomial variance is one thing; 100 samples is another).

### I5. The "operational definition of flag" trigger surface is large and the trigger decision is implementer judgment (overengineering)

The 4-tier flag operational definition (lines 36–43) requires:
1. Structured anomaly artifact
2. WARN log
3. Open-questions entry (only when "recurring decision class")
4. Non-silent commit

Trigger surface I count from the epic:
- S03.3 — "If extraction surfaces a license/season pattern that doesn't fit"
- S03.4 — closure temporal anchors deferral, BMU-region map fallback
- S03.5 — unmatched / unlinked descriptions
- S03.6 — additional statewide regulation_record candidates
- S03.7 — A/B-pattern model-fit anomalies
- S03.8 — `parameters` deferral cases (V1: `900-20`; potentially others)
- S03.9 — HD→region mapping anomalies
- S03.10 — no-hunt-zone Option B/C escalation
- S03.11 — calibration audit findings

That's ~9 distinct flag-trigger surfaces. The "open-questions entry only when recurring decision class" is rule (3); the implementer must decide whether each flag is "recurring." That's judgment, not mechanism.

**Concrete risk:** an implementer writes a working-note entry, a WARN log, and a run-summary count for `900-20`'s deferral and stops — never adds to `open-questions.md`. Six months later in M2, the question of "what other deferrals match this class?" has no anchor in `open-questions.md`. The flag is durable in `E03-deferred-items/draw-mechanics.md` but invisible to the question-tracking flow ADR-009 establishes.

**Proposed fix:** flip rule 3 from "only when recurring" to "**always**, with a one-line description; PM optionally consolidates duplicates later." Or, alternatively, give the implementer a concrete test: "if more than one entry exists in any single `E03-deferred-items/<topic>.md` file, an `open-questions.md` entry is required." Either makes the trigger mechanical, not judgment-dependent.

### I6. S03.7 weapon convention is correct but interacts badly with S03.3's extraction artifact (best practices)

**Line 580:** `license_tag.weapon_types` is "required array. The license is the source of truth for 'what weapons can this hunter use.'"

**S03.3's artifact schema (line 277):** `"weapon_types": ["any_legal_weapon"]` — but this is shown as the field on a `row` (a license row), not on the season. S03.3's schema does NOT have a per-season weapon_type — it has `season_coverage.archery_only: true/false`.

**Mapping ambiguity:** when S03.7 reads "Archery Only" as a season name (line 569) and writes `season_definition.name="Archery Only"`, what's `season_definition.weapon_type`? The epic at line 579 says the season "imposes a weapon constraint (e.g., the Archery Only season has `weapon_type='archery'`)." But S03.3's extraction artifact only has the season name — there's no per-season `weapon_type` field in the JSON.

**Proposed fix:** S03.3's `season_windows` payload should include a `weapon_type_override: "archery" | None` field for seasons that are explicitly weapon-restricted. Currently the inference is "if name == 'Archery Only', weapon_type='archery'; else NULL" which is a magic-string convention. Add to S03.3's AC: "extraction emits `weapon_type_override` per season window, derived from the source's column header (e.g., 'ARCHERY ONLY' → `archery`); other columns (`GENERAL`, `LATE`) emit `None`." Add to S03.7's AC: "writes `season_definition.weapon_type` from `weapon_type_override`."

Otherwise S03.7 is doing string-matching on a name that came from a separate extraction artifact, which is brittle.

---

## Minor findings / nits

- **N1 — S03.0 "pre-approved" interpretation is correct but should be reinforced.** Line 120: "architecture.md §'Schema types': `LicenseSeason` interface + `Geometry.legal_description` + `kind='state'` documented (per ADR-018 §'Three-place sync' — pre-approved by the ADR sign-off, no separate human gate)." This is consistent with the user's standing instruction (PM can edit thinking-layer docs only when explicitly authorized; ADR-018 §"Three-place sync" provides that explicit authorization). Worth keeping; consider adding a sentence "this exception is narrow — only the type-stub-mirror update; any prose-section additions to architecture.md still require user approval."

- **N2 — Estimated row counts are estimates, not assertions.** S03.6 line 484 says "**~514 regulation_record rows**" but AC line 536 wisely says "approximately 514 rows… may differ." Same pattern in S03.7, S03.8, S03.10. This is fine — but consider adding a "fail loud if count is < 70% or > 130% of estimate" guard rail to detect catastrophic regressions. Right now a script that produces 50 rows when 514 expected would log success.

- **N3 — `EXPECTED_RA_ORPHAN_IDS` is referenced but never enumerated in E03.** Line 54 references "`EXPECTED_RA_ORPHAN_IDS` allowlist (3 IDs)" with names "Glacier NP, Sun River Game Preserve, Yellowstone NP." The literal IDs aren't given. Implementer must read E02's `build_overlay_fixture.py` to find them. Add the 3 IDs inline in S03.10 context.

- **N4 — `verbatim_rule` empty-string contract is not propagated to S03.5/S03.6.** The known-pitfalls.md notes that `verbatim_rule` columns silently accept `""`. S03.5 produces `verbatim_description` strings; S03.6 writes them to `legal_description`. The same pitfall applies — empty strings will silently land. Add an AC: "S03.6 rejects empty/whitespace-only `legal_description` strings (writes NULL instead)."

- **N5 — Schema validator references (F10, F12, B1, B2, S5, SF2, SF5, SF6, N2, N3, N4, N5) are opaque to readers without the underlying validator artifact.** This is fine if the validator output is committed somewhere and discoverable. If not, every reference is "trust me, the validator said so." Either commit the validator output adjacent to the epic or inline the validator's actual rule into the epic context. Long-term durability concern: in M3 someone reading this epic without the validator output won't be able to reverse-engineer the rule.

- **N6 — S03.1's SHA-drift marker file mechanism doesn't handle URL drift.** Line 165 covers content drift (SHA changes); line 148 says "TBD — discoverable from FWP 'errata' or 'corrections' pages" for the correction PDF URL. If FWP redesigns their site and the URL 404s, the fetcher raises (likely a 4xx) but doesn't write a marker. Add to S03.1 AC: "404/connection errors during fetch raise `PdfFetchError` with the source URL in the message; downstream stories detect the missing fixture file as the gating signal (no separate URL-drift marker)."

- **N7 — S03.12's "user pushes the m1 tag" delineation is correct per user's standing instruction (no push by agent).** Line 946: "user pushes m1 tag." Good — matches the MEMORY.md "no push or PR creation" convention. Worth explicitly calling out in the AC list ("agent commits the working-notes deletion + handoff + UAT artifacts; user runs `git tag m1 && git push --tags`").

- **N8 — S03.0 "create both directories with README" is fine, but `.gitignore` post-M1 update is queued for S03.12.** Line 884 says S03.12 updates `.gitignore` to prevent re-creation. Reasonable. But the deletion in S03.12 is `git rm -r`, which doesn't auto-update .gitignore — implementer must do both. AC line 944 says "Calibration findings directory deleted (`git rm -r docs/planning/epics/E03-confidence-findings/`); `.gitignore` updated" — good, both included.

---

## Strengths (genuine signal)

- **E02-mirror patterns are clean and load-bearing.** S03.0 mirrors S02.0; S03.1's PDF fetch infrastructure mirrors S02.1's ArcGIS infrastructure (sources.yaml, manifest convention, gitignored payloads, polite throttling, drift policy). A reviewer can validate the patterns without re-reasoning every story. The known-pitfalls.md "drift-signal artifacts must write a marker for the empty case" pattern is correctly applied via the SHA-drift marker file in S03.1.

- **ADR-017 and ADR-018 are already accepted, with explicit deferral paths.** The "OR-ed conditions" deferral test in ADR-017 §7 + the auto-defer fallback in S03.11 (line 877–880) is a legitimately good piece of risk management — it ensures the milestone tag never blocks on an open ADR amendment.

- **Cross-species filter is correctly identified as load-bearing** (the per-species axis multiplication of overlay fixture rows is real). The implementation specification has a bug (C1 above), but the spec correctly identifies that without this filter the binding count would be wrong by a factor of ~3 for shared-namespace HDs.

- **Per-cell date-arbitration is the correct model** for corrections (vs. per-row replacement). Lines 364–366 and the AC at line 397 both pin this down. The 2026-03-18 correction column-removal case is genuinely cell-level.

- **Concrete row-count estimates throughout** (514 regulation_records, ~600-1,000 season_definitions, ~3,000-6,000 license_seasons, ~280-700 draw_specs, ~6-10 reporting_obligations, 1,500-3,500 jurisdiction_bindings) give sanity-check anchors. ACs correctly soften them to "approximately" but include them as expected-magnitude verification.

- **UAT-yes/UAT-no per-story decisions are well-motivated.** S03.3, S03.4, S03.5 (per-booklet faithfulness — must verify against source PDF, can't be tested mechanically), S03.7 (load-bearing A/B asymmetric coverage — milestone criterion #2), S03.10 (cross-species filter is novel logic), S03.12 (milestone exit). Stories that just write rows from clean intermediates are UAT-no.

- **The "spatial entities are outside ADR-017's framework" carve-out** (line 30 + line 826 AC: "`confidence` not written") is correctly threaded through S03.10. This is the kind of detail that gets dropped during implementation; the explicit AC is good defense.

- **ADR-018's three-coordinated-additions-in-one-migration model** correctly anticipates that fragmenting these into 3 separate migrations would have been worse. S03.0 ships the single migration cleanly.

- **S03.7's distinction between `season_definition.weapon_type` and `license_tag.weapon_types`** (lines 578–582) is correctly identified as load-bearing. The semantic ("intersection at render time") is correctly deferred to M3.

- **The deferred-items survival policy** (lines 64–65) is the right call. M2 PM handoff has durable artifacts; M1 working notes (calibration findings) correctly die at the m1 tag. The two-directory split is worth the small overhead.

---

## Recommended next actions

1. **Re-walk S03.10 cross-species filter against the actual `geometry-overlays.json` namespace patterns** (C1 is the highest-impact finding — it would silently produce zero portion bindings for elk/mule_deer/whitetail). Update the filter rule to be per-species-namespace, not per-shared-deer-elk-lion-namespace. Verify whitetail handling specifically (no `MT-HD-whitetail-` portion layer exists in E02 per the CLAUDE.md summary).
2. **Add explicit ACs for**: C2 (date collision tiebreaker + missing-date fail-loud), C3 (S03.5 produces JSON only), C4 (S03.7 leaves `draw_spec_key` NULL; S03.8 backfills via UPDATE), C5 (tier-rank MIN, not lexicographic), I2 (S03.5 unmatched-threshold fail-loud), I3 (S03.10 zero-binding-no-hunt-zone fail-loud), I4 (audit math when stratified > 50), I6 (S03.3 emits per-season `weapon_type_override`).
3. **Optional but worth considering before merge**: tighten the "open-questions entry" rule (I5) to a mechanical trigger; enumerate the 3 RA orphan IDs inline in S03.10 (N3); inline the schema-validator rules referenced as "F10, F12, etc." (N5) so the epic is self-contained.

Total fix surface is ~12 AC additions/clarifications + 1 structural rule rewrite (C1). After those land, the epic is implementable.
