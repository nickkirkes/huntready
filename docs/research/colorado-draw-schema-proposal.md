# Colorado Draw System — Schema Modeling Proposal

**Status:** Draft for review
**Date:** 2026-04-19
**Scope:** Extend the HuntReady regulation schema to represent limited-draw mechanics across Colorado, Wyoming, New Mexico, and Utah. Colorado is the stress-test case.
**Hard constraint:** The proposed schema must handle CO, WY, and NM without state-specific fields or code paths in shared code. State-specific logic lives in the state adapter.

---

## 1. How Colorado's draw works

Colorado Parks and Wildlife (CPW) runs a three-stage annual cycle — a **primary draw** in May, a **secondary draw** in late June for unsold licenses, and a weekly **leftover list** starting in early August. Only the primary draw is point-aware; the later two are pure random / first-come. Applicants accrue one preference point per species per year either by applying unsuccessfully for a first-choice hunt code or by explicitly applying for a species-specific *point-only code* (e.g., `E-P-999-99-P` for elk). Points reset to zero when an applicant draws their first-choice hunt code. They do **not** reset when an applicant draws on choice 2, 3, or 4 (choices beyond the first are filled via random draw from remaining licenses and do not consume points).

Within the primary draw, CPW uses two allocation rules depending on demand. For ordinary hunt codes, 100% of licenses are allocated by descending preference-point rank — the applicants with the most points are drawn first, with ties broken randomly. For *hybrid-eligible* hunt codes — defined as hunt codes where the three-year rolling average (with a one-year lag) of resident preference points required to draw was six or more — CPW splits the allocation: **80% is allocated by descending preference-point rank**, and **20% is allocated via an unweighted random draw among applicants with at least five preference points**. The five-point floor and 80/20 split are administrative parameters that CPW can (and has) adjusted; a 50/50 rule for all species is slated for 2028.

Non-resident allocation operates as a ceiling *on top of* the draw pools, not as a separate pool. Any single hunt code can award **up to 20%** of its licenses to non-residents if the three-year rolling point requirement is six or more, or **up to 25%** if it is fewer than six. Residents and non-residents draw from the same preference-point ranking; the cap truncates the non-resident winners if the cap would otherwise be exceeded, and the displaced licenses fall back to residents at the next point tier. Unit-level quotas themselves are set annually by CPW based on population modeling, prior harvest, and management objectives, and are published in the Colorado Big Game Brochure as rows keyed on a structured hunt code (`[species]-[GMU letter]-[hunt number]-[season/weapon]-[residency]`).

Sources: CPW Primary Draw, Secondary Draw, and Nonresidents pages on cpw.state.co.us; 2026 Colorado Big Game Brochure (CPW Widen portal).

---

## 2. Worked example

**Applicant.** A non-resident with 5 elk preference points applies to the 2026 primary draw with the following choices:

1. `E-E-024-O1-R` — a hybrid-eligible elk hunt code (high-demand, historical ≥6 point requirement, so the hybrid 80/20 rule applies)
2. `E-E-045-O1-R` — a lower-demand hunt code (standard preference-point draw)
3. `E-P-999-99-P` — elk point-only code

Call the hunt code's total quota *Q₁* (we'll use 25 for illustration — the actual 2026 value is published per-unit in the brochure). The hard non-resident ceiling is 20% of *Q₁* = 5 tags.

**Choice 1 evaluation.** The hybrid rule applies.

- **Preference-point pool (80% × 25 = 20 tags).** Tags are awarded top-down by point count, residents and non-residents competing in the same ranking. If the point line falls at 8, applicants with 8+ points fill the 20 tags. Our applicant has 5 points and does **not** win here.
- **Random pool (20% × 25 = 5 tags).** Drawn unweighted from applicants with ≥5 preference points who did not win in the preference pool. Suppose the eligible pool is 120 applicants (residents + non-residents with 5–7 points). The raw draw odds are 5 / 120 ≈ **4.2%** per applicant.
- **Non-resident ceiling.** After both pools draw, CPW enforces the 20% NR cap across the combined 25-tag allocation. If the two pools together awarded more than 5 tags to non-residents, the excess is reassigned to the next-best resident(s). This can slightly lower non-resident realized odds below the raw random-pool odds.

With 5 points on a hybrid unit whose point line is 8, our applicant's realistic odds for Choice 1 are roughly **3–5%**.

**Choice 2 evaluation (if Choice 1 lost).** Any licenses remaining for `E-E-045-O1-R` after that hunt code's own Choice 1 round are filled by unweighted random among everyone who listed it as Choice 2. Points are not used. If Choice 2 awards a license, the applicant keeps their 5 points (no reset). If it does not, no point is awarded.

**Choice 3 evaluation (point-only).** If Choices 1 and 2 both fail, the applicant's final selection is the point-only code. They receive 1 preference point, ending the 2026 cycle at **6 points** for 2027.

**Expected outcome.** Across 100 hypothetical identical applicants, roughly 3–5 would draw the Choice 1 hybrid unit, roughly 20–30 would draw Choice 2 depending on that hunt's Choice-2 demand, and the remainder would finish the year with a point accrual but no tag. The specific numbers move with the real Choice-2 field sizes, which are published in CPW's annual big-game statistics reports.

---

## 3. Comparative summary

**Wyoming.** Preference-point system with a deterministic split: 75% of each hunt-code's tags go to applicants ranked top-down by points (ties broken randomly), and 25% go to an **unweighted** random draw open to all applicants regardless of points. Resident / non-resident allocation is a hard statutory split per species (roughly 90/10 for elk, 80/20 for antelope and deer, with further carve-outs for special vs. regular tag tiers that have their own draw pools). Points are lost after two consecutive years of inactivity.

**New Mexico.** No points at all. Tags are filled by pure unweighted random draw. Residency allocation is a statutory three-way carve-out enforced *before* the draw runs: 84% to residents, 10% to anyone (resident or non-resident) hunting under a signed outfitter contract, 6% to unguided non-residents. Each of these is effectively its own random pool. The absence of a points mechanism is the most important structural difference from the other three states — it cannot be modeled as "Colorado with 0% preference-point share."

**Utah.** Bonus-point system for limited-entry and once-in-a-lifetime hunts, with a 50/50 allocation split: 50% of tags go top-down to applicants with the most bonus points, and 50% go to a **weighted** random draw where each applicant's bonus points are *squared* and treated as the number of draw entries. Residency carve-out is 90% resident / 10% non-resident. Utah also operates a separate *preference-point* system for general-season hunts, so a single species (e.g., elk) is governed by two different point systems depending on which hunt code a tag belongs to.

**Common conceptual elements.** All four states encode: a hunt code, a total quota per hunt code, a residency allocation rule, zero or more allocation pools with a share and a selection algorithm, and optionally a per-species point mechanism. The mechanical variation lives almost entirely in two axes — **point system** (none / preference-linear / bonus-squared) and **selection algorithm per pool** (rank-ordered / unweighted-random / squared-weighted-random). State-specific quirks — WY special vs. regular tiers, NM outfitter contract semantics, UT youth allocation, CO point-only code naming — are parameters and metadata, not mechanics.

---

## 4. Schema options evaluated

**Option 1 — Extend `tag_info` with optional draw fields.** Add flat fields (`draw_algorithm`, `preference_point_share`, `min_points_threshold`, `nonresident_cap`, etc.) directly to `tag_info`. Most states' tags leave most of them null. **Verdict:** The null density becomes meaningful — "null" in `preference_point_share` ambiguously means either "100% preference points" (Colorado non-hybrid) or "no points system" (New Mexico). Multiple allocation pools per tag (NM's three pools; CO's hybrid 80/20) force the flat model to either pick one pool as "canonical" or degrade to parallel-arrays-by-suffix. Poor fit.

**Option 2 — Sibling `draw_spec` entity with a discriminator.** Move draw mechanics into a dedicated entity joined to the regulation record by `hunt_code`. The entity carries structured fields: `point_system`, `choices`, `residency_cap`, and an array of `allocation_pool` rows each with a `share`, `selection_method`, and `eligibility` predicate. A discriminator enum names the selection method per pool. **Verdict:** Cleanly represents the one-to-many relationship between a hunt code and its allocation pools. Every state populates the same fields; differences are values, not presence-or-absence of columns. Readable by SQL, queryable by the MCP server without deserializing JSON. Costs one additional table and one join per tag lookup.

**Option 3 — `jsonb` blob with a minimal structured envelope.** Keep a small structured envelope on `tag_info` (`draw_type`, `application_deadline`, `purchase_url`) and drop a `draw_spec jsonb` field containing the full mechanics document. **Verdict:** Maximum flexibility, minimum query power. The MCP server cannot efficiently answer "which hunt codes require ≥5 points" or "which units reserve ≥10% for non-residents" without scanning every row. More importantly, the lack of a structured contract means each state adapter invents its own shape — which directly violates the hard constraint that shared code must not branch on state. `jsonb` has a role in this schema, but as an *escape hatch* for state adapter metadata, not as the primary representation.

---

## 5. Recommendation

**Option 2, augmented with a narrow `parameters jsonb` escape hatch.**

The sibling entity carries all fields that shared code reads. Everything state-specific — WY tier pricing, NM outfitter contract references, UT youth allocation metadata — goes into `parameters`. Shared code never reads `parameters`; state adapters produce it during normalization and consume it during display or analytics. This keeps the hard constraint intact: the MCP server's `get_tag_requirements` tool branches on `point_system.kind` and `pool.selection_method` (enumerated, state-neutral) but never on `state`.

---

## 6. Proposed schema

### TypeScript

```typescript
// A regulation record's tag_info gains an optional pointer to a draw_spec by hunt_code.
interface TagInfo {
  required: boolean;
  type: "general" | "limited_draw" | "over_the_counter";
  application_deadline?: string;   // ISO 8601
  purchase_url: string;
  hunt_code?: string;              // stable ID; foreign key to draw_spec.hunt_code
}

interface DrawSpec {
  schema_version: number;
  hunt_code: string;               // e.g. "CO:E-E-024-O1"; globally unique
  state: string;                   // ISO-3166-2, e.g. "US-CO" (for routing, not for logic)
  quota: number | null;            // total tags; null if variable or unpublished
  point_system: PointSystem | null;      // null = no points (e.g. New Mexico)
  residency_cap: ResidencyCap | null;    // top-level NR ceiling; null if residency is encoded in pools
  choices: ChoiceConfig;
  pools: AllocationPool[];         // shares must sum to 1.0
  draw_phase: "primary" | "secondary" | "leftover";
  successor_hunt_code?: string;    // next phase's hunt_code, for primary -> secondary chains
  parameters?: Record<string, unknown>; // state-adapter escape hatch; not read by shared code
  source: { url: string; publication_date: string };
}

type PointSystem = {
  kind: "preference_linear" | "bonus_squared" | "bonus_weighted";
  accrual: "annual_on_apply" | "annual_if_purchased";
  reset_on_success: boolean;
  purchase_only_code?: string;     // e.g. "E-P-999-99-P" for CO elk
  inactive_forfeit_years?: number; // e.g. 2 for WY
};

type ResidencyCap = {
  nonresident_max_share: number;   // 0.0 – 1.0; applied after pool draws
};

type ChoiceConfig = {
  count: number;                   // e.g. 4 in CO, 3 in NM
  points_used_in_choices: number[]; // e.g. [1] for CO, [] for NM
};

type AllocationPool = {
  share: number;                   // 0.0 – 1.0
  selection: "rank_ordered_by_points"
           | "unweighted_random"
           | "squared_weighted_random"
           | "linear_weighted_random";
  eligibility: {
    min_points?: number;
    residency?: "resident" | "nonresident" | "any";
    guided?: boolean;              // NM outfitter pool; unset elsewhere
  };
  tie_break?: "random" | "rank_ordered";
};
```

### Postgres DDL

```sql
create table draw_spec (
  hunt_code             text primary key,
  schema_version        integer not null,
  state                 text not null,                 -- routing/display only
  quota                 integer,                       -- nullable
  point_system          jsonb,                         -- PointSystem | null
  residency_cap         jsonb,                         -- ResidencyCap | null
  choices               jsonb not null,                -- ChoiceConfig
  pools                 jsonb not null,                -- AllocationPool[]
  draw_phase            text not null
                        check (draw_phase in ('primary','secondary','leftover')),
  successor_hunt_code   text references draw_spec(hunt_code),
  parameters            jsonb,                         -- state-adapter extension
  source_url            text not null,
  source_publication    date not null,
  created_at            timestamptz not null default now()
);

-- link from the regulation record's tag_info (which lives on regulation_record)
alter table regulation_record
  add column tag_info_hunt_code text references draw_spec(hunt_code);

-- query-side indexes
create index draw_spec_state_phase_idx on draw_spec (state, draw_phase);
create index draw_spec_min_points_idx on draw_spec ((pools -> 0 -> 'eligibility' ->> 'min_points'));
```

`point_system`, `residency_cap`, `choices`, and `pools` are stored as `jsonb` for write ergonomics and schema-version flexibility, but their shape is contractually defined in the TypeScript interfaces above and validated on write. This is the structured-envelope-over-jsonb pattern: the columns are typed and queryable; the *values* are documented objects, not free-form blobs.

---

## 7. Representation examples

**Colorado — hybrid-eligible elk unit (E-E-024):**

```json
{
  "hunt_code": "CO:E-E-024-O1",
  "state": "US-CO",
  "quota": 25,
  "point_system": {
    "kind": "preference_linear",
    "accrual": "annual_on_apply",
    "reset_on_success": true,
    "purchase_only_code": "E-P-999-99-P"
  },
  "residency_cap": { "nonresident_max_share": 0.20 },
  "choices": { "count": 4, "points_used_in_choices": [1] },
  "pools": [
    {
      "share": 0.80,
      "selection": "rank_ordered_by_points",
      "eligibility": {},
      "tie_break": "random"
    },
    {
      "share": 0.20,
      "selection": "unweighted_random",
      "eligibility": { "min_points": 5 }
    }
  ],
  "draw_phase": "primary",
  "successor_hunt_code": "CO:E-E-024-O1:SECONDARY"
}
```

**Wyoming — elk hunt code (random 25% pool open to all points):**

```json
{
  "hunt_code": "WY:EL-001-REG",
  "state": "US-WY",
  "quota": 40,
  "point_system": {
    "kind": "preference_linear",
    "accrual": "annual_if_purchased",
    "reset_on_success": true,
    "inactive_forfeit_years": 2
  },
  "residency_cap": { "nonresident_max_share": 0.10 },
  "choices": { "count": 3, "points_used_in_choices": [1] },
  "pools": [
    {
      "share": 0.75,
      "selection": "rank_ordered_by_points",
      "eligibility": {},
      "tie_break": "random"
    },
    {
      "share": 0.25,
      "selection": "unweighted_random",
      "eligibility": {}
    }
  ],
  "draw_phase": "primary",
  "parameters": { "tier": "regular" }
}
```

**New Mexico — elk hunt code (three statutory pools, no points):**

```json
{
  "hunt_code": "NM:ELK-15-RIFLE",
  "state": "US-NM",
  "quota": 50,
  "point_system": null,
  "residency_cap": null,
  "choices": { "count": 3, "points_used_in_choices": [] },
  "pools": [
    {
      "share": 0.84,
      "selection": "unweighted_random",
      "eligibility": { "residency": "resident" }
    },
    {
      "share": 0.10,
      "selection": "unweighted_random",
      "eligibility": { "guided": true }
    },
    {
      "share": 0.06,
      "selection": "unweighted_random",
      "eligibility": { "residency": "nonresident", "guided": false }
    }
  ],
  "draw_phase": "primary"
}
```

Hard-constraint check: the three records above differ only in values (including which fields are `null`), never in presence of state-specific columns. Shared code reads the same fields in the same order for all three. Utah maps cleanly onto the same shape using `"kind": "bonus_squared"` and `"selection": "squared_weighted_random"`; it is omitted here only for brevity.

---

## 8. Likely future pressure points

- **CPW's 2028 reform.** CPW has approved a shift to a 50/50 preference-point / random split on all limited-draw big game. This is a value change, not a structural change — the schema accommodates it by updating `pools[0].share` and `pools[1].share`. Flagged so the 2028 migration path is anticipated, not surprising.
- **Squared-weighted and higher-order point math.** Utah's squared bonus is already represented. If a state adopts cubed points, a *function-of-points* formula, or age-weighted points, the `selection` enum grows one more value. If more than one state invents its own math, we may regret the enum and should consider a formula-string representation (e.g., a small DSL) at that point — not before.
- **Draw-inside-a-draw.** Colorado's `secondary` draw against leftovers from `primary`, and some states' sheep/goat draws that branch from a successful-elk-applicant pool, are modeled as separate `draw_spec` rows connected by `successor_hunt_code`. If a state ever runs a *nested* draw — a single primary draw whose losers are re-evaluated in a second pool before results are published — the current sibling-row model will feel awkward. A nested `pools` structure (tree, not list) would handle it; defer until the first real case.
- **Eligibility predicates beyond min_points / residency / guided.** Youth allocation (UT), landowner preference (WY), hunter-education vintage rules (various) all push eligibility into a richer predicate. We can add named booleans as they arise; if we hit a combinatorial explosion, consider a small rule expression DSL. Until then, add discrete fields.
- **Weighted preference points for moose / sheep / goat in Colorado.** CPW uses an exponential-weighting variant (`random_number / (weighted_points + 1)`) for species with hard 3-point caps. This is a `linear_weighted_random` selection variant and is already representable; flagged here because it's a CO-specific quirk that will need an explicit record in the first CO ingestion sprint.
- **Residency cap enforcement ordering.** The current schema encodes NR caps as a single post-draw ceiling. A few states apply residency caps *within* each allocation pool rather than across the combined draw. If we encounter this, `AllocationPool.eligibility.residency` already handles it — we'd model such a hunt code with per-pool residency eligibility and no top-level `residency_cap`. Flagged so reviewers know this was considered, not forgotten.
- **Point banking, transfer, and retirement.** None of the four V1 states allow points to be transferred between hunters. If a state ever does (the topic surfaces periodically in legislative proposals), the `point_system` object grows a `transferable: boolean` field — a non-breaking addition.

---

## 9. Open questions for review

- Is `hunt_code` the right primary key, or should `draw_spec` be keyed by `(state, hunt_code, year)` to support year-over-year changes without rewriting history? *Lean toward composite key; flagged for the ADR.*
- Where does `application_deadline` live — on `tag_info`, on `draw_spec`, or both? Deadlines vary by draw phase, which suggests `draw_spec`, but it is historically on `tag_info`. *Recommendation: move to `draw_spec`; deprecate on `tag_info` in next schema version.*
- Should `draw_phase` be an enum or a structured object with start/end dates? For V1, enum is sufficient; dates are on the regulation record already.

---

## Sources

- [Colorado Parks and Wildlife — Primary Draw](https://cpw.state.co.us/activities/hunting/big-game/primary-draw)
- [Colorado Parks and Wildlife — Secondary Draw](https://cpw.state.co.us/activities/hunting/big-game/secondary-draw)
- [Colorado Parks and Wildlife — Nonresidents](https://cpw.state.co.us/activities/hunting/nonresidents)
- [Colorado 2026 Big Game Brochure (CPW)](https://cpw.widen.net/s/5wvx7rggrd/colorado-big-game-hunting-brochure)
- [Wyoming Game & Fish — Understanding the Draw](https://wgfd.wyo.gov/wyoming-wildlife/wyoming-wildlife-magazine/understanding-draw)
- [Wyoming Game & Fish — Draw Results & Odds](https://wgfd.wyo.gov/licenses-applications/draw-results-odds)
- [New Mexico Department of Game & Fish — How the Draw Works](https://wildlife.dgf.nm.gov/hunting/applications-and-draw-information/how-new-mexico-draw-works/)
- [Utah Division of Wildlife Resources — Big Game Odds & Points Report](https://wildlife.utah.gov/bg-odds.html)
- [Utah Big Game Application Guidebook 2026 (DWR)](https://wildlife.utah.gov/guidebooks/biggameapp.pdf)
