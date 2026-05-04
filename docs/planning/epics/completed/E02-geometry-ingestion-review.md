# E02 Epic Review

**Epic:** docs/planning/epics/E02-geometry-ingestion.md
**Reviewer:** Ruckus epic-reviewer (model: opus)
**Date:** 2026-04-28
**Status when reviewed:** Not Started (E01 complete and merged)

---

## Summary verdict

**Needs Revision** (small set of concrete edits — not a rework)

The epic is unusually thorough: it correctly diagnoses and resolves the PRD/schema FK conflict, plans for the well-known ArcGIS pagination/projection gotchas, mirrors E01's three-place-sync and runbook conventions, and uses sensible PostGIS casting for the geography vs. geometry containment problem. There are, however, a small number of concrete blocking issues: a missing migration deliverable for the `gis_layer` document_type (S02.0 lists Pydantic/TS additions but the migration line only mentions `verbatim_rule`); two factual PostGIS claims that are partially wrong (`ST_Contains` *does* exist for geography in PostGIS 2.4+, and the `&&` operator does not exist for `geography` so the cast pattern needs adjustment); a verbatim-text concatenation rule in S02.4 that risks editorializing under ADR-008; and a "geom byte-equality" reproducibility test in S02.7 that will not work as written. None of these require restructuring the story map; they are edits.

---

## Findings by dimension

### 1. Technical accuracy

**[High] S02.6 line 380, S02.7 line 475: `ST_Contains` and `ST_Overlaps` claim is misleading.** The epic says "`ST_Contains` and `ST_Overlaps` do not exist for `geography` type." This is wrong as stated — PostGIS has had `ST_Covers(geography, geography)`, `ST_Intersects(geography, geography)`, and (since 2.4) a limited `ST_Contains(geography, geography)`/`ST_Within(geography, geography)` for some cases. The accurate reason to prefer `ST_Covers` over `ST_Contains` is semantic (boundary inclusion) and historical (`ST_Contains` for geography is partial — it works for the same-precision case but not the general case, and PostGIS docs explicitly recommend `ST_Covers` for geography). Replace the "do not exist" claim with: "Prefer `ST_Covers`/`ST_Intersects` on geography (or cast to geometry); avoid `ST_Contains`/`ST_Overlaps` because their geography support is partial and semantically surprising for boundary-touching cases." Otherwise, an implementation agent will write `ST_Covers(a.geom, b.geom)` (no cast) and it will work — contradicting the epic's prescribed pattern and confusing reviewers.

**[High] S02.6 line 391: `&&` operator and the `::geometry` cast.** The query reads `WHERE a.geom::geometry && b.geom::geometry AND ST_Covers(a.geom::geometry, b.geom::geometry)`. The intent (use the GiST index via the bounding-box pre-filter) is correct, but PostGIS GiST indexes on a `geography` column index that geography type. Casting to geometry in the WHERE clause may not use the existing `geometry_geom_gix` index defined in E01 (which is on `(geom)` of geography, not `(geom::geometry)`). The right fix is one of:
- Use `ST_Intersects(a.geom, b.geom)` directly on geography — PostGIS will use the GiST index on geography and `ST_Intersects` then handles the spheroid math. For containment, use `ST_Covers(a.geom, b.geom)` directly.
- Or, if you need geometry-domain semantics, add a separate functional index on `(geom::geometry)` in S02.0 or S02.6.

The current AC ("EXPLAIN ANALYZE shows `Index Scan using geometry_geom_gix`") will likely **fail** if the cast pattern is used as written — PostGIS will not use a geography GiST index for a `geometry`-domain `&&`. Fix the SQL or document a functional index.

**[High] S02.7 AC line 500: "geom byte-equality" reproducibility is not realistic.** PostGIS round-trips through `geography(MultiPolygon, 4326)` involve internal canonicalization (ring orientation, point ordering normalization in some cases, EWKB encoding). Even if you re-fetch the identical GeoJSON and apply identical `make_valid()`, the resulting EWKB may differ across rounds in subtle ways (e.g., when a geometry passes through `ST_Multi` or a `make_valid` branch that re-orders ring vertices nondeterministically). Practical reproducibility tests should compare:
- `ST_Equals(a, b) = true` (topological equality), or
- `ST_HausdorffDistance(a, b) < epsilon` (geometric near-equality), or
- WKB hash of a normalized form (`ST_Normalize`).

Replace "geom byte-equality" with "`ST_Equals(geom, prior_geom)` returns true for every row" or equivalent.

**[High] S02.0 deliverable list lines 53-63 vs. AC line 71: missing migration for `document_type='gis_layer'`.** The "Migration deliverables" section says "1. New migration adding `'gis_layer'` to `source` jsonb's `document_type` enum (Postgres can't enforce jsonb-internal CHECK constraints, so this is enforced in Pydantic + TypeScript only)." That's contradictory — if it's enforced only in Pydantic/TS, there is no migration for it. The AC at line 71 only lists the `verbatim_rule` migration. So the deliverable list is misleading. Either:
- Drop the phrase "New migration" for the gis_layer change and rely on the type-layer enforcement (and document the architecture.md doc update as the "migration"), or
- Add a no-op migration that documents the change for the migration-trail audit. Pick one and state it clearly.

**[Medium] S02.0 AC line 70 / line 75: Pydantic `Geometry` model already handles WKT validation but `verbatim_rule: str | None = None` addition needs to interact with the existing `_validate_geom` validator.** Confirm in the AC that adding the new field doesn't break `model_config = ConfigDict(frozen=True, extra="forbid")` — adding a field to a frozen model is fine, but anyone constructing `Geometry` instances from existing test fixtures must update them or the `extra="forbid"` will reject older payloads if any exist. There is no production data yet so this is low-risk in practice; flag it in the AC anyway.

**[Medium] S02.1 §8 line 144-150: `geojson_to_multipolygon_wkt` pipeline silently elides `GeometryCollection → polygonal-only` filtering.** The pipeline says "if `GeometryCollection` → filter to polygonal members, union, wrap." Filtering and unioning loses information silently — non-polygonal members (lines, points) may signal a data-quality problem worth surfacing rather than swallowing. The contract should be: "if `GeometryCollection` and any non-polygonal members exist, raise (with the OBJECTID and feature attributes in the message). If all members are polygonal, union and wrap." This is consistent with the rest of the library's "fail loudly" philosophy stated elsewhere in §8.

**[Medium] S02.1 §3 line 117: `pyproj.Transformer` dependency.** `pyproj` is not declared in `ingestion/pyproject.toml` (only `geopandas`, `shapely`, etc., are). `geopandas` pulls `pyproj` transitively, so it's available, but the AC list should include "`pyproj` is declared as a direct dependency in `pyproject.toml`" since the library imports it directly. Otherwise a future `geopandas` removal would silently break the reprojection fallback.

**[Medium] S02.5 line 347: "update their `kind` from `'restricted_area'` to `'cwd_zone'`" creates an idempotency hole.** S02.4 inserts these as `restricted_area`. S02.5 then mutates `kind` for matching rows. Re-running S02.4 after S02.5 will UPSERT the rows back to `restricted_area` (because S02.4's `INSERT ... ON CONFLICT (id) DO UPDATE SET ...` does not include `kind` in its excluded columns — and even if it did, S02.4 hard-codes `kind='restricted_area'`). The CWD reclassification will be silently undone by the next ingestion run. Either:
- S02.5 inserts CWD zones as new rows with new IDs (preferred — preserves S02.4's source-of-truth), or
- S02.4 explicitly skips rows that should be `cwd_zone` (requires S02.5 to inform S02.4 — a circular dep), or
- The reclassification is captured as an exclusion list S02.4 reads.

This is genuinely subtle and worth flagging before someone implements S02.4 + S02.5 and ships it.

**[Medium] S02.0 line 55: jsonb-internal CHECK on document_type.** The epic says "Postgres can't enforce jsonb-internal CHECK constraints." That's wrong — Postgres absolutely can: `CHECK ((source->>'document_type') IN ('annual_regulations', 'rule_change', 'emergency_order', 'correction', 'gis_layer'))`. The current schema (S01.2) doesn't use such a check, and adding one across all `source` columns would be a substantial scope add — but the assertion should be corrected. If you want the check, it can be added; if you choose not to, document why (e.g., flexibility for future enums, accepted drift cost).

**[Low] S02.0 line 161 in S02.1: `editingInfo.lastEditDate`.** This is a Unix epoch in milliseconds, not a date string, in the ArcGIS metadata response. The `SourceCitation.publication_date: str` field is documented in architecture.md as ISO date. The `or fetch_date` fallback handles missing values, but if `lastEditDate` is present, it must be converted to ISO before use. Add this conversion explicitly to the AC for S02.1.

**[Low] S02.4 line 306: Concatenation of REG + COMMENTS.** The concatenation `f"{REG}\n\n{COMMENTS}"` introduces a separator that is itself an editorial decision. ADR-008 says verbatim text is preserved; concatenating two adjacent verbatim strings with a fixed separator does not violate ADR-008 in spirit but does insert non-source content between them. A safer alternative: store both fields separately. Options:
- Add a second field on `geometry` (`verbatim_comments text`). Heavier-weight schema change.
- Encode as JSON: `verbatim_rule = json.dumps({"reg": REG, "comments": COMMENTS})`. Defeats the readable-text purpose.
- Accept the concatenation but document in S02.4 that the `\n\n--- COMMENTS ---\n\n` separator is a HuntReady-introduced delimiter, not source content; future consumers should be aware.

This is a real ADR-008 ambiguity worth flagging explicitly, not a "if it proves to need separate handling" note. Recommend either splitting into two columns or owning the separator decision in S02.0's ADR scope.

### 2. Best practices

**[Low] Mirrors E01 conventions well.** Per-story ACs, three-place sync verification, runbook deliverable (`docs/runbooks/E02-geometry-verification.md`), schema-version-aware migration discipline. The epic structure follows E01 closely — this is a strength.

**[Medium] Path inconsistency: `ingestion/ingestion/lib/arcgis.py` (S02.1) vs. `ingestion/states/montana/load_hds.py` (S02.2).** The library lives inside the Python package (correct — it's importable), but the state adapter lives outside. Looking at the actual repo: `ingestion/ingestion/lib/schema.py` exists (inside package); `ingestion/states/montana/` exists (at top level, currently empty). This is consistent with what E01 settled on — but the import path from a state adapter at `ingestion/states/montana/` to a library at `ingestion/ingestion/lib/` requires either making `ingestion/states/` a package too (add `__init__.py`), making it a separate top-level package, or adjusting the layout. Either path is fine; the epic should call it out so an implementation agent doesn't burn time discovering it. Recommend adding an explicit note in S02.1 or S02.2: "State adapter import pattern — confirm and document during S02.2."

**[Low] No mention of pgvector or any extension beyond PostGIS.** Just confirming — none needed. The schema as set up by E01 is sufficient.

### 3. Risks

**[High] S02.5 fallback-path acceptance criterion is too permissive.** AC: "If no GIS source: epic file's 'Deferred items' section updated... no `cwd_zone` rows written." This permits a story to "succeed" with zero CWD zones loaded, which materially affects M1 outcome (CWD reporting obligations are mentioned in PRD 001 line 47, and PRD success criterion 3 references "any overlay BMU, CWD zone, or Portion"). If S02.5 punts to E03, E03 must hand-trace polygons from the Legal Descriptions PDF — that is a substantial scope addition for E03 that this epic does not estimate. Either:
- Hard-block the epic on a finding (escalate to PM): "If S02.5 cannot ingest CWD zones from a GIS source, the M1 success criterion 3 is at risk and PRD 001 needs reconciliation."
- Or, define a third fallback: hand-traced polygons in `ingestion/states/montana/cwd-zones-manual.geojson` checked into the repo, ingested via the same load path with `confidence: 'low'` and a note in the SourceCitation that they were hand-traced from the PDF. This aligns with ADR-008's confidence-low handling.

**[High] License-year handling: `REGYEAR` may be NULL.** The schema (`geometry.license_year integer NULLABLE` from S01.2 line 175) allows NULL — confirmed by reading the migration. So this is not a blocker, but the epic should make it explicit: "When REGYEAR is absent or NULL in the source, `license_year` is written as NULL, not as the current year. NULL signals 'year-invariant' or 'unknown' — the schema accepts this." Currently lines 203-205 of the table say "if `REGYEAR` exists use that, else NULL" but it's worth restating in the AC: "AC: rows with no source REGYEAR have `license_year = NULL` (verified by SELECT)."

**[Medium] Idempotency hash machinery in S02.1 §5 is a moving-target risk.** The hash includes `geometry_wkt` which is shapely-canonicalized output. A `shapely` upgrade (2.0 → 2.1, etc.) could change WKT canonicalization (e.g., float precision in coordinate output) and thus change the hash even though the source data is identical. The mitigation is `geometryPrecision=7` on the ArcGIS query (which truncates server-side) plus relying on `make_valid` to be deterministic. Worth a comment in the library: "Layer hash invariance is conditional on shapely version; on shapely upgrade, expect a one-time hash bust per layer."

**[Medium] S02.7 reproducibility AC requires "wipe geometry rows" — but the migration RLS denies anon. Service-role bypass works, but DELETE from a foreign-key-bearing table needs care once jurisdiction_binding is populated.** In E02 standalone, no FKs to geometry exist (jurisdiction_binding is E03). So `DELETE FROM geometry` is fine right now. Worth noting in the runbook that this pattern only works for the E02 standalone state and changes once E03 lands.

**[Medium] The `&&` bounding-box pre-filter in S02.6 is relevant only for cross-product queries on large datasets.** Montana has ~200 HDs. A nested-loop seq-scan against ~200 × ~50 portions ≈ 10K rows is sub-second. The performance AC ("EXPLAIN ANALYZE shows Index Scan") may be premature optimization — and as flagged above, may not even succeed with the cast pattern. Soften to "EXPLAIN ANALYZE shows reasonable plan; document whatever PostGIS chooses."

### 4. Overengineering

**[Medium] S02.1 §4 hash-suffixed historical fixtures + symlinks (line 124).** "Optionally: hash-suffixed historical copies + `<service>-<layer_id>-latest.{json,geojson}` symlinks for `ls`-based diff." This is speculative — V1 has no consumer for diff-by-hash other than humans running `ls`. Git itself tracks history; symlinks add cross-platform fragility (Windows). Recommend: drop the symlink scheme; rely on git history for diffs. Reduces friction and avoids "Why are these symlinks broken on this developer's checkout?" debugging.

**[Low] S02.1 §5 idempotency hash machinery (lines 126-130).** Building a per-feature canonical hash + layer-level hash is a real engineering investment. The benefit is "skip re-fetch if unchanged." For V1 with manual ingestion, "skip re-fetch" saves seconds at most. The cost is the canonicalization logic (which has the version-fragility risk noted above), test coverage for hash stability, and maintenance. Recommendation: keep the per-feature hash for *change detection* (i.e., logging "feature X changed since last fetch") but defer the layer-level hash + skip-re-fetch optimization until a real performance issue emerges. This trims S02.1's surface area without losing the audit value.

**[Low] S02.1 §8 GeometryCollection unioning.** Real ArcGIS Polygon layers should never return GeometryCollection. If one does, that's a data-quality signal worth surfacing, not handling. Replace "filter to polygonal members, union, wrap" with "raise an error with the offending feature ID and field values." Less code, safer outcome.

### 5. Acceptance criteria quality

**[High] S02.5 AC: "Libby CWD Management Zone (or equivalent named zone) is queryable."** "or equivalent" allows the story to pass without verifying any specific known zone. UAT spot-checks must be specific: "Test point `(48.388, -115.555)` (somewhere known to be in the Libby CWD area) returns `kind='cwd_zone'` row whose name contains 'Libby' or 'CWD'." Or: name three specific Montana CWD zones from the FWP regulation booklet and test all three. Without specificity, the UAT is unverifiable.

**[Medium] S02.6 AC: "every row in `geometry` table appears in the fixture as parent or child of at least one relationship."** This is good, but it should also assert that *every* geometry has a `self` row with `role_for_e03='primary_unit'` *only if* it's a hunting district. A Portion or Restricted Area should not have a `primary_unit` self-row — it has a `portion` or `restricted_area` row pointing to its parent HD. Strengthen to: "every hunting_district row has a self-relationship with `role_for_e03='primary_unit'`; every portion, cwd_zone, restricted_area row appears as `child_geometry_id` in at least one relationship to a hunting_district parent."

**[Medium] S02.2 AC line 234: `ST_GeometryType(geom::geometry) returns only ST_MultiPolygon`.** Good — but `ST_NumGeometries(geom::geometry) > 1` (line 235) only requires *at least one* multi-part HD. For Montana specifically, name a known multi-part HD (e.g., HDs along the Idaho or Wyoming border) and assert *that specific HD* is multi-part. Otherwise, a single accidentally-multi-part geometry passes the test even if the rest collapsed to single-polygon when they shouldn't have.

**[Medium] S02.2 AC line 238: `license_year = 2026` for layer #11.** Hardcoding 2026 in an AC is fragile — if the test runs in 2027 against fresh data, it fails. Better: "license_year matches the REGYEAR field from the metadata fixture; for the 2026 fetch, that value is 2026." Pin the test to the data, not the calendar.

**[Low] S02.4 AC line 324: "If `REG` or `COMMENTS` is empty/whitespace, `verbatim_rule = NULL`".** Fine, but consider: what if `REG` is populated and `COMMENTS` is empty? The concatenation rule says concatenate when both differ — what about when one is missing? Spell out: "If only REG is populated, use REG. If only COMMENTS is populated, use COMMENTS. If both populated and differ, concatenate. If both empty, NULL."

### 6. Dependencies

**[Low] S02.1 dependency on S02.0 is partial.** S02.1 only needs the `document_type='gis_layer'` Pydantic Literal (for the SourceCitation construction at line 161) and the `Geometry.verbatim_rule` field (for type-checking the helper signature). The migrations themselves can land in parallel with S02.1 development as long as both ship before S02.2 runs. Worth documenting: "S02.1 needs the type updates (Pydantic + TS) from S02.0 to compile; the migration is needed only before S02.2 inserts data." This unblocks parallelism within E02 development.

**[Medium] S02.2 / S02.3 / S02.4 truly are parallelizable.** The parallelization note (line 533) says they're theoretically parallel but recommends sequential. Three separate state-adapter files writing to different `kind` values with disjoint ID prefixes — they have no shared write conflicts. If implementation bandwidth allows, parallel is fine. Recommend changing "sequential simplifies coordination" to a softer "sequential is the default; parallel is acceptable if branch-management cost is low."

**[Low] S02.6 dependency line 446: "Depends on: S02.2, S02.3, S02.4, S02.5".** S02.5 is the conditional one — if S02.5 ingests no CWD zones, S02.6 still works (one less relationship type). Should explicitly note: "S02.5 outcome may be empty; S02.6 produces fixture with HD↔CWD relationships only if S02.5 loaded CWD zones."

**[Low] Deferral to E03 of jurisdiction_binding.** Section 20-26 handles this well. One missing detail: E03 will need to know the *fixture schema* it's consuming. A small JSON Schema or TypedDict for the fixture format would let E03 type-check its consumer. Add an AC to S02.6: "Fixture schema documented in `ingestion/states/montana/fixtures/geometry-overlays.schema.json` or an inline section of the epic." Otherwise E03 will reverse-engineer the format from sample rows.

---

## Specific suggestions for improvement

- **S02.0 line 53-55:** Resolve the migration vs. type-layer-only contradiction for `document_type='gis_layer'`. Either drop the "new migration" claim or add a documentation-only migration for audit trail.
- **S02.0 line 55:** Correct the "Postgres can't enforce jsonb-internal CHECK" claim — it can; the choice is whether to.
- **S02.1 §3:** Add `pyproj` to `ingestion/pyproject.toml` as a direct dependency.
- **S02.1 §5:** Drop the layer-level hash skip-re-fetch optimization for V1; keep per-feature hash for change-detection logging only.
- **S02.1 §4:** Drop the symlink-based latest-fixture scheme; rely on git history.
- **S02.1 §8:** Change GeometryCollection handling from "union polygonal members" to "raise loudly with feature context."
- **S02.1 line 161:** Convert `editingInfo.lastEditDate` (epoch ms) to ISO date in the SourceCitation construction; add to AC.
- **S02.2 AC lines 234-238:** Pin multi-part HD verification to a *named* HD; pin license_year assertion to "matches REGYEAR from metadata fixture" not "= 2026."
- **S02.4 line 306:** Decide REG+COMMENTS handling deliberately — split column or own the separator. Update ADR-015 scope or add ADR-016 if splitting.
- **S02.4 AC line 324:** Spell out all four cases (REG only, COMMENTS only, both populated, both empty).
- **S02.5 AC line 362:** Replace "Libby CWD Management Zone (or equivalent)" with three specific named zones from the FWP regulation booklet.
- **S02.5:** Add a third fallback path — hand-traced GeoJSON in the repo with `confidence='low'` — and update the decision tree at lines 350-352. Avoid leaving M1 success criterion 3 dependent on E03 hand-tracing.
- **S02.5:** Document the kind-mutation idempotency hole (S02.4 will UPSERT the rows back to `restricted_area`); choose either separate IDs for CWD zones or an exclusion list.
- **S02.6 line 380:** Rewrite the PostGIS-operators-on-geography section accurately. `ST_Contains` does exist for geography but is partial; recommend `ST_Covers`/`ST_Intersects` for semantic reasons.
- **S02.6 line 391:** Drop the `::geometry` cast in the `&&` and `ST_Covers`/`ST_Intersects` calls, or document that a functional index on `(geom::geometry)` will be created. Verify the GiST index is actually used by the chosen pattern.
- **S02.6:** Add fixture-schema documentation as an AC (JSON Schema or inline TypedDict).
- **S02.6 line 452:** Strengthen "every row appears as parent or child" to specify which `role_for_e03` each kind should produce.
- **S02.7 AC line 500:** Replace "geom byte-equality" with "`ST_Equals(geom_after_reload, geom_before_reload)` is true for every id" or hash of `ST_Normalize(geom)`.
- **S02.7:** Add coordinate fixture spec — at least one test point per HD/Portion/Restricted Area kind, named explicitly with expected resolution rather than "≥3."
- **Section "Parallelization Notes" line 533:** Soften the sequential-only recommendation for S02.2-S02.4 — they are genuinely parallelizable.
- **Section "Known issues to escalate":** Add a fifth entry: "PostGIS operator semantics on geography type — verify the chosen `ST_Covers` + cast pattern against actual EXPLAIN output before locking in S02.6 query patterns."

---

## Strengths worth preserving

- The PRD/schema FK conflict is diagnosed cleanly and resolved with the geometry-overlay-fixture handoff to E03 — that is exactly the right call and the rationale at lines 20-27 is rigorous.
- S02.1's enumeration of ArcGIS gotchas (`orderByFields`, `exceededTransferLimit`, error envelope, Web Mercator masquerading as 4326, `returnTrueCurves=false`) is the kind of operational knowledge that prevents three-day debug rabbit holes.
- The `kind='hunting_district'` clarification for layer #10 (lines 207-209) — distinguishing FWP's Black Bear Hunting Districts from true ecological BMUs — captures a real semantic gotcha and keeps `bear_management_unit` available as a future binding role without conflating geometry classification.
- Species-prefixed deterministic IDs (`MT-HD-deer-elk-lion-262-geom`) correctly anticipate cross-layer HD-number collisions.
- The three-place sync discipline carries over cleanly from E01.
- E01-style runbook deliverable (`docs/runbooks/E02-geometry-verification.md`) and per-story ACs are consistent with what E01 established.
- The "no `AREA_*` columns" rule in S02.4 (line 308) — single source of truth via `ST_Area` — is the right discipline.
- The deferred-items list (lines 539-545) is honest about BMA and ecological-BMU scope cuts.
