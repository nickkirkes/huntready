# Investigation — MT `regulation_record` 435 (dev) vs 437 (prod-anchored)

**Date:** 2026-07-02
**Author:** PM Agent (Claude Code session)
**Scope:** dev-side + doc-side only. Zero prod writes, zero `ingestion/` code changes, no epic edits, no new ADRs.
**Verdict:** **No dev/prod divergence exists.** Both dev and prod DB read **435** MT `regulation_record` rows. **437 is the loader _build_ count**, which UPSERT-collapses to 435 in the DB (2 rows merge on the composite PK). The prior "2-row pronghorn delta / dev never received the post-S03.6.1 build" narrative is a **misdiagnosis of the already-documented build-vs-DB gap**.
**Disposition:** **Option A (accept + document)** — refined: there is nothing to backfill (dev already equals prod). Correct the M2-uat runbook and the M2→M3 handoff, which are the only two docs carrying the false divergence narrative.

---

## Root cause in one paragraph

The `load_regulation_records.py` loader constructs **437** rows in memory (its final log line reads `total | 437`) and writes them via `INSERT … ON CONFLICT (state, jurisdiction_code, species_group, license_year) DO UPDATE`. **2 of those 437 build-rows share a composite PK** ("cross-species near-duplicates" per the M1 UAT capture) and therefore UPSERT-merge, leaving **435 rows** in the DB. This is deterministic: the same frozen loader against the same committed extraction artifacts yields the same 435 DB rows on **every** environment. Prod landed at 435 (M1 UAT, 2026-05-28). Dev landed at 435 (M2-build + Group B passes, 2026-06-23 / 2026-07-01). They match exactly.

---

## Q1 — Where exactly is the delta?

**There is no delta.** Both environments read 435. The apparent "gap" is loader **build count (437)** vs post-UPSERT **DB count (435)**.

Authoritative DB counts (no live SQL needed — see "Why no live SQL" below):

| Source | Environment | `regulation_record` (MT) DB count | Provenance |
|---|---|---|---|
| `docs/runbooks/M1-uat-results-2026-05-28.md` line 222 | **prod** | **435** | M1 UAT idempotency table (baseline 435 = post-rerun 435 ✓), main @ `a4657b2` |
| `docs/runbooks/M1-uat-results-2026-05-28.md` line 187 | **prod** | **435** | criterion #4 ("0 leaks across 435 regulation_record rows") |
| `docs/runbooks/M2-uat.md` line 381 (group-b Z-1…Z-4) | **dev** | **435** | E06 Group B pass, 2026-07-01 |
| `docs/planning/prds/002-M2-colorado-ingestion.md` line 15 | **prod-anchor** | **435** | "435 regulation records … all **post-UPSERT DB counts** … build-side projections are larger and collapse via `ON CONFLICT DO UPDATE`" |

The 437 figure is a **build count** everywhere it appears in a DB context:
- `M1-uat-results-2026-05-28.md` line 231: loader emits `total | 437` (labeled "(build)").
- `M1-uat-results-2026-05-28.md` line 245 footnote: `regulation_record | 437 build | 435 DB | −2 | 2 PK collapses (cross-species near-duplicates)`.
- `docs/planning/handoffs/M1-to-M2-handoff.md` §3 line 184: "regulation_record 437 build → 435 DB … Entity tables collapse via `INSERT … ON CONFLICT DO UPDATE`."

The prior "2 pronghorn HD rows" characterization was attached to a **delta that does not exist**; it is not a missing-pronghorn issue. The 2 collapsing rows are two build-rows sharing a composite PK (per the M1 UAT footnote); their exact identity is not independently re-derivable here (the S03.6 working note that would detail it was deleted at `m1` per ADR-017 §6), but it is immaterial — both environments run the identical deterministic loader and land at the identical 435.

## Q2 — Which loader run(s) never happened on dev?

**None.** `git log -- ingestion/states/montana/load_regulation_records.py` shows exactly three commits: `c0c1b77` (S03.6), `339e213` (S03.6.1), `a4657b2` (S03.12). The S03.12 diff on that file changes **only docstrings and error-message strings** — no row-output change. The loader has been **output-frozen since S03.6.1**. Dev and prod both ran this frozen loader against the same committed artifacts (`dea-2026.json`, `black-bear-2026.json`), so both produce 437 build → 435 DB.

Hypothesis **H1** ("dev never ran the post-S03.6.1 loader chain / dev is short 2 rows vs prod") is **refuted**: the M1 UAT prod capture shows **prod itself is 435**, not 437. There is no state in which prod ever held 437 DB rows for dev to be "missing."

## Q3 — Which chronology explains the gap?

**Neither H1 nor H2** — the gap is not a chronology divergence at all. It is the **build-vs-DB UPSERT-collapse gap**, which was already identified, root-caused, and documented at M1 close:
- `M1-uat-results-2026-05-28.md` §"Footnote — runbook expected-count discrepancy" (lines 241–257).
- `M1-to-M2-handoff.md` §3 convention note (line 45) + §8 fix #4 (line 184).
- `M1-uat.md` §4 criterion #6 (build-vs-DB footnote, landed at S04.4).

The M2-uat.md `[^devprod]` footnote (authored during E06 Group B / S06.11 close) re-interpreted this known build-vs-DB gap as a fresh "dev vs prod divergence" and invented the "dev never received the post-S03.6.1 pronghorn build" cause. That reinterpretation is wrong; PRD 002 SC #9's own baseline (435, post-UPSERT DB) contradicts it.

---

## Why no live SQL was run

The three investigation questions are answered conclusively by committed evidence, and live SQL would add no information while carrying real risk:
1. **Both DB counts are already captured** — prod 435 (M1 UAT, authoritative service-role `SELECT COUNT(*)`) and dev 435 (Group B pass, 2026-07-01). They agree.
2. **The loader is output-frozen and deterministic** against committed artifacts, so dev's 435 is byte-identically prod's 435 — a live per-species breakdown would be identical on both and cannot surface a divergence that the deterministic pipeline forbids.
3. **DSN ambiguity risk** — the local `DATABASE_URL` is service-role and, in the M1 UAT, pointed at **prod**. Running ad-hoc SQL risks touching the wrong project. The constraint is dev-side/read-only; committed captures already satisfy it without that risk.

---

## Disposition — Option A (accept + document), refined

There is no divergence to accept and nothing to backfill (Option B is moot). The corrective action is to stop two docs from asserting a false "437 prod / 435 dev / 2-pronghorn-missing" divergence and make the MT baseline unambiguous for the operator's prod pass:

- **`docs/runbooks/M2-uat.md`** — rewrite the `[^devprod]` footnote and the six sites derived from it to state: **MT `regulation_record` DB baseline = 435 on both dev and prod; 437 is the loader build count (2 PK collapses); SC #9 asserts the DB count 435.** (Done in the same change as this note.)
- **`docs/planning/handoffs/M2-to-M3-handoff.md`** — correct §"Final counts" line 68 + its `[^devprod]` footnote so M3 does not inherit the false narrative. (Done.)
- **No PRD edit** — `docs/planning/prds/002-M2-colorado-ingestion.md` line 15 is already correct (435 post-UPSERT DB). The prompt's premise that "SC #9 cites 437" was itself inherited from the buggy M2-uat.md footnote.
- **No `ingestion/` change, no migration, no ADR, no epic edit.**

**Net effect for the prod M2-release pass:** the operator asserts MT `regulation_record` = **435** (DB). If the prod loader's log shows `total | 437` build, that is expected and correct — it collapses to 435 in the DB, exactly as M1 UAT captured on 2026-05-28.

---

## Audit trail / references

- Prod M1 UAT capture: `docs/runbooks/M1-uat-results-2026-05-28.md` (lines 187, 222, 231, 241–257)
- M1→M2 handoff build-vs-DB: `docs/planning/handoffs/M1-to-M2-handoff.md` §3 (lines 45, 184)
- M1 UAT runbook build-vs-DB footnote: `docs/runbooks/M1-uat.md` §4 criterion #6
- PRD 002 authoritative MT DB counts: `docs/planning/prds/002-M2-colorado-ingestion.md` line 15 + SC #9 (line ~128) + closing build-vs-DB note
- Dev captures: `docs/runbooks/M2-uat.md` line 381 (group-b Z-1…Z-4, 2026-07-01) + `docs/runbooks/M2-operator-pass.md` (M2-build pass, 2026-06-23)
- Loader history: `git log -- ingestion/states/montana/load_regulation_records.py` (`c0c1b77`, `339e213`, `a4657b2`)
