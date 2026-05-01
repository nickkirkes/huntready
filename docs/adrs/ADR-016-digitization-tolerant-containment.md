# ADR-016: Digitization-Tolerant Containment for Geometry Overlays

**Date:** 2026-05
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** ingestion, schema, geometry, e02, e03

---

## Context

[E02 S02.6](../planning/epics/E02-geometry-ingestion.md) computes the overlay fixture E03 will consume to populate `jurisdiction_binding` rows. The fixture captures HD↔Portion, HD↔CWD-zone, and HD↔Restricted-Area spatial relationships. The original epic spec (lines 478–496) prescribed `ST_Covers(geog, geog)` for HD→Portion containment and `ST_Intersects + ST_Covers` discriminator for HD→CWD/RA, with a coverage invariant requiring every Portion / CWD / RA to appear as a child of at least one HD.

Two separate problems emerged when the spec met the live Montana data:

1. **Strict `ST_Covers` rejects portions due to digitization precision.** Portions are subdivisions of HDs and *should* sit cleanly inside their parent HD's polygon. In practice, the source GIS data has portion edges that fall fractions of a meter outside the parent HD boundary because the two layers were digitized independently. Result: only 23 of 55 Montana portions pass strict `ST_Covers`; the other 32 share the parent HD's edge but extend slightly past it. Strict adherence to the spec would orphan these portions and fail the build.

2. **Boundary-touching produces noise.** Adjacent HDs share boundary edges. Any spatial predicate broader than strict `Covers` — `Intersects`, `Touches`, geometric overlap of any size — produces row pairs for *every* shared-boundary case. With 235 HDs, the average HD shares boundaries with ~6 neighbors. Without filtering, the fixture grows from "HD-X owns portion Y" relationships to "every neighboring HD also touches portion Y at a single shared edge", giving 7+ candidate parents per child. E03 cannot distinguish the real parent from the boundary-edge noise.

3. **A semantic edge case the spec did not anticipate.** Three of Montana's 57 restricted areas — Glacier National Park, Sun River Game Preserve, Yellowstone National Park — are no-hunt zones. They are surrounded by HDs but, geometrically, do not overlap them at all (max ~0.04% area touching at sliver-edges). The spec's coverage invariant treats every restricted_area as needing an HD parent; these national-park-style zones legitimately have none.

Spec-faithful implementation cannot satisfy both (1) "portions get covers relationships" and (2) "the fixture isn't dominated by boundary noise" with a single PostGIS predicate. The data carries two distinct kinds of relationship — *containment* (modulo precision) and *boundary-edge contact* — and the fixture needs to disambiguate them.

## Decision

Replace the binary "covers vs not-covers" PostGIS predicate with a **three-band area-ratio threshold** computed locally in shapely:

```
overlap_pct = parent_geom.intersection(child_geom).area / child_geom.area

overlap_pct >= COVER_RELABEL_THRESHOLD (0.99) -> relationship = "covers"
overlap_pct <  COVER_DROP_THRESHOLD    (0.01) -> drop the row, write to audit log
otherwise                                      -> relationship = "intersects"
```

The thresholds are constants at the top of `ingestion/states/montana/build_overlay_fixture.py`. Dropped rows are written to `ingestion/states/montana/fixtures/geometry-overlays-dropped.json` (committed) so a future reviewer can verify nothing semantically real was discarded — filtering is one-way.

The coverage invariant is relaxed for `restricted_area` only. Portions and CWD zones must still appear as children of at least one HD (raises `OverlayFixtureError` on orphan); restricted-area orphans are surfaced via INFO log and allowed through. The carve-out is named in code (`_ORPHAN_FAILS_INVARIANT`) and pointed at this ADR.

## Reasoning

**Why the area ratio, not shapely's `covers` predicate.** `parent.covers(child)` is a topological boolean: it returns True if and only if every point of `child` is inside or on the boundary of `parent`. It is exactly as strict as `ST_Covers`, and it carries the same digitization-precision failure mode. The area ratio is a *quantitative* measure that admits a tolerance ("at least 99% of the child sits inside the parent — close enough to call this containment given the source data's edge precision").

**Why `child.area` as the denominator (asymmetric).** The semantic question E03 asks the fixture is "what HDs is this Portion / CWD / Restricted-Area a child of?" — the relationship is keyed off the child. A small child (a portion) inside a large HD has high `intersection.area / child.area` (≈ 1.0); a small child grazing the corner of a much larger HD has low `intersection.area / child.area` (≈ 0). Symmetry would muddy this: `intersection.area / parent.area` would relabel a small-portion-in-huge-HD case as `intersects` simply because the child occupies a small fraction of the parent. The asymmetric ratio is the right one for this use.

**Why 0.99 and 0.01.** Empirically calibrated against the Montana dataset:

| Bucket | Portion count | Restricted-area count | Interpretation |
| --- | --- | --- | --- |
| `>= 99%` | 102 | 49 | Containment (digitization-tolerant) |
| `50%-99%` | 15 | 30 | Substantial overlap |
| `5%-50%` | 6 | 39 | Real partial overlap |
| `0.1%-5%` | 26 | 33 | Edge-near-misses |
| `< 0.1%` | 262 | 76 | Boundary-touching only |

The `>= 99%` band cleanly separates the digitization cluster (mostly 99.5–99.99%) from substantial-but-not-containing overlaps (50–99%). The `< 1%` band cleanly separates pure boundary-touching (mostly < 0.1%) from genuine partial overlaps (1–50%). Wider thresholds (e.g., 0.95 / 0.05) let digitization noise leak into "covers" and edge slivers leak into "intersects"; tighter thresholds (e.g., 0.999 / 0.001) reject borderline-real cases. The 0.99 / 0.01 pair is conservative on both ends.

**Why the audit log is committed alongside the fixture.** Filtering is one-way: dropped pairs are not reachable from `geometry-overlays.json`. A future reviewer asking "why doesn't HD-262 list the bordering portion-X?" needs the answer in source control, not in a rerun. The audit gives them one — `(parent_id, child_id, parent_kind, child_kind, overlap_pct)` per dropped pair, with `overlap_pct` rounded to 6 decimal places for byte-deterministic JSON.

**Why restricted_area orphans are allowed but portion/CWD orphans still raise.** Portions are by definition subdivisions of one HD; an orphan portion is a real data-quality bug worth raising loudly. CWD zones are management areas defined relative to HDs; an orphan CWD is similarly a data error. Restricted areas are a mixed bag — most are HD-internal restrictions (archery-only zones inside a single HD), but a documented subset are "no-hunt" zones (national parks, game preserves) that are *adjacent to* but not *contained within* HDs. Treating all three kinds identically would either tolerate real bugs in the first two (relaxing all) or fail the build on legitimate national-park geometry (raising all). The split keeps fail-loud discipline where it should be loud and information-flow where it should be informational.

**Why this decision is load-bearing.** The thresholds, denominator choice, and orphan policy together define how E03 will populate `jurisdiction_binding` rows for V1 and how the MCP server's spatial query results map to regulations. Any future state's overlay computation will face the same digitization-precision question; this ADR is the contract those state adapters either reuse or deliberately diverge from.

## Alternatives Considered

**Use strict `ST_Covers` and accept the build failure.** Rejected: 32 of 55 portions become orphans on real Montana data. The build fails loudly, but the underlying issue (digitization precision) is a property of the source GIS data that HuntReady cannot fix. Rejecting the data forces every state's source maintainer to re-digitize their layers to sub-meter precision before HuntReady will accept them — not a viable contract.

**Use strict `ST_Covers` plus a buffered fallback (`ST_Covers(ST_Buffer(parent, tol), child)`).** Rejected: introduces a second tolerance parameter without solving the boundary-noise problem. Buffering by ~1 meter still produces "intersects" rows for every shared-boundary HD neighbor.

**Use `ST_Intersects` only, no `ST_Covers` at all.** Rejected: produces the noisy 967-row fixture observed in the live build before this decision. Median 6 candidate parents per child; HD-262 alone had 4 boundary-touch rows, none of which were its real children.

**Use the symmetric ratio `max(intersection / parent.area, intersection / child.area)`.** Rejected: the asymmetric child-keyed ratio is what the consumer (E03) needs. Symmetry helps for the small-parent-in-large-child direction, but in V1 every parent is a hunting district that is *larger than* most of its children (portions, CWD zones, restricted areas), so the symmetric path adds complexity without changing the result.

**Apply per-child-kind thresholds (e.g., 0.95 for portions, 0.50 for CWDs).** Rejected: the same digitization-vs-noise distinction applies to all three child kinds. Variable thresholds would require per-kind empirical calibration and complicate the audit log's "this dropped pair would have been kept under what threshold?" question. The single 0.99 / 0.01 pair is the minimum number of constants the rule needs.

**Pre-process the GIS data to snap portion edges to HD edges before ingestion.** Rejected: an upstream solution to a downstream problem. HuntReady's role per [ADR-001](ADR-001-authority-preserved-not-replaced.md) is to route hunters to authoritative source data, not to reshape the source. Edge-snapping would constitute paraphrase of source geometry — a categorical break with the verbatim discipline.

**Store the relationship label as a continuous score (`overlap_pct`) instead of a discrete `covers` / `intersects`.** Rejected: E03's `jurisdiction_binding.role` enum is discrete, and downstream consumers (MCP server, web composer) make discrete choices. A continuous score forces every consumer to pick a threshold, which is exactly the decision this ADR makes once for the whole stack.

**Drop the audit log; rely on rebuilding to re-derive dropped pairs.** Rejected: the source GIS data drifts (FWP republishes layers; we re-fetch quarterly per [E02 S02.2 idempotency notes](../planning/epics/E02-geometry-ingestion.md)). A reviewer asking about a dropped pair from a *previous* fixture build cannot reproduce that drop without snapshotting the historical source. The audit captures the answer at build time.

## Consequences

### Positive

- All 55 Montana portions appear as children of an HD via `covers` — the spec's coverage invariant is met by the relaxed-but-not-broken interpretation.
- Boundary-touching noise is removed from the kept fixture: 967 rows → 586 rows on Montana data, parents-per-child median drops from ~6 to ~3.
- The audit log gives a future reviewer a complete record of what was filtered and why, with byte-deterministic ordering for diff-friendly review.
- The `restricted_area`-orphan carve-out has a documented justification (national parks, game preserves) and a code comment pointing here.
- The thresholds are explicit constants, not magic numbers — `COVER_RELABEL_THRESHOLD` and `COVER_DROP_THRESHOLD` are importable for tests and for any future state's overlay computation that wants to reuse the same calibration.

### Negative

- The kept fixture is no longer a pure derivation from PostGIS predicates: a reader of the fixture cannot reproduce it from `ST_Covers` / `ST_Intersects` alone. They need this ADR plus the threshold constants. The audit log mitigates but does not eliminate this opacity.
- The 0.99 / 0.01 calibration is empirical — Montana-specific. A future state with a different digitization regime (e.g., sub-meter LiDAR-derived boundaries) might want tighter thresholds; one with coarser source data might want looser. The constants live in the Montana adapter today; lifting them to shared code with per-state overrides is a future tax.
- The `restricted_area`-orphan carve-out shifts the failure mode from "build fails" to "INFO log + orphan list in the fixture-builder log line". A reviewer who skims past INFO lines could miss a real RA-coverage bug introduced by a future change. Mitigation: the INFO line names the count and the offending IDs explicitly; pre-commit log review remains a human discipline.

### Neutral

- The decision is implemented in `ingestion/states/montana/build_overlay_fixture.py` only. The Montana-specific location is correct for V1 (only Montana has loaded data) but means a future state's adapter must either import the thresholds from a yet-to-exist shared module or duplicate them with a cross-reference here. Decision deferred to the second-state work.
- The audit JSON (`geometry-overlays-dropped.json`) is committed alongside the kept fixture. Both files are small (~hundreds of rows × ~150 bytes each ≈ tens of KB), well within the existing `ingestion/states/montana/fixtures/` directory's commit policy.

## Links

- [ADR-001](ADR-001-authority-preserved-not-replaced.md) — Verbatim discipline; this ADR's edge-snapping rejection rests on it.
- [ADR-008](ADR-008-verbatim-regulation-text.md) — Verbatim regulation text; sibling discipline.
- [ADR-010](ADR-010-decomposed-entity-model.md) — The entity model; `geometry` and `jurisdiction_binding` live here.
- [ADR-014](ADR-014-source-citation-gis-layer-document-type.md) — `document_type='gis_layer'`; the type-layer geometries this ADR computes overlays for.
- [ADR-015](ADR-015-geometry-verbatim-rule-and-reg-comments-handling.md) — Sibling decision shape; ADR-016 follows the same authoring pattern (empirical calibration, separator/threshold contracts, edge-case documentation).
- [`docs/planning/epics/E02-geometry-ingestion.md`](../planning/epics/E02-geometry-ingestion.md) — § S02.6 is the originating context.
- [`ingestion/states/montana/build_overlay_fixture.py`](../../ingestion/states/montana/build_overlay_fixture.py) — Implementation.
- [`ingestion/states/montana/fixtures/geometry-overlays-dropped.json`](../../ingestion/states/montana/fixtures/geometry-overlays-dropped.json) — Audit log artifact.
