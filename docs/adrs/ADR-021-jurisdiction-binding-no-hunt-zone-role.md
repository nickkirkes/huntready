# ADR-021: Jurisdiction-Binding `no_hunt_zone` Role Enum

**Date:** 2026-06-03
**Status:** Accepted
**Decider:** Nick Kirkes
**Tags:** schema, ingestion

> Status note: `Accepted` as of S05.3.5 — the five-place sync + MT V1 data reclassification shipped via migration `20260603000000_jurisdiction_binding_no_hunt_zone_role.sql`. (`Proposed` pre-implementation convention per `docs/adrs/README.md` §"Status".)

---

## Context

`jurisdiction_binding.role` carries a 7-value CHECK constraint at `supabase/migrations/20260425000000_initial_schema.sql:201-206` (`primary_unit`, `portion`, `restricted_area`, `cwd_management_zone`, `bear_management_unit`, `block_management_area`, `other_overlay`). M1 Montana V1 bound 3 federal no-hunt zones as `role='other_overlay'` because the enum carried no value for categorical hunt-closure overlays. Handoff §8 #4 flagged this as semantically imprecise but tolerable at MT volume.

M2 Colorado triggers the decision. S05.4 research at `docs/research/colorado-restricted-areas-evaluation.md` (PAD-US 4.1, live-probed 2026-06-03) identifies 10 V1-scoped CO no-hunt zones (4 NPs + 5 NMs + the AFA; enumerated in the research doc's Outcome section). The load-bearing argument is semantic precision, not volume: NPs/NMs and the AFA are PERMANENT statutory closures (NPS Organic Act 16 USC §1, per-park enabling legislation, DOD installation rules) — categorically different from the weapon-type or season-window overlays the existing role values describe. A client calling `check_land_status` cannot distinguish "rule restricts your weapon" from "you cannot hunt here at all" while both bind as `other_overlay`.

## Decision

Add `'no_hunt_zone'` to the `jurisdiction_binding.role` CHECK constraint as an 8th value, propagate via five-place sync (DDL migration + Pydantic Literal + TypeScript union + `docs/architecture.md` §"Schema types" + `ingestion/ingestion/lib/overlays.py`'s `GeometryRoleForE03` Literal alias), and reclassify MT V1's 3 existing no-hunt-zone bindings from `'other_overlay'` to `'no_hunt_zone'` in the same migration.

## Reasoning

### 1. Role encodes the regulatory relationship, not a residual bucket

ADR-010 frames `jurisdiction_binding.role` as the categorical relationship between a `regulation_record` and a `geometry`. `'other_overlay'` is residual — for relationships the model has not yet named. Using it for federal categorical hunt-closure (a relationship the project now knows it has) erodes the discipline. CO surfaces 10 such bindings; every future western state will surface analogous NPS / DOD / FWS no-hunt overlays. The pattern is general; the value belongs in the enum.

### 2. The MCP response envelope needs the distinction

Per ADR-002, `check_land_status` is the canonical "can I hunt at this coordinate?" tool. Per ADR-013, the server returns structure; the client composes presentation. A client cannot compose a "no hunting here" response from `role='other_overlay'` because that value also covers archery-only overlays inside HDs. The `check_land_status` response shape is not yet specified (`docs/architecture.md` L85 describes the tool but does not bind `jurisdiction_binding.role` to an envelope field); this ADR commits the schema-side distinction so a future M3 ADR can render it as a discriminator. The role enum is necessary-but-not-sufficient for the cited consumer benefit.

### 3. Small migration, precedented shape

ADR-018 is the closest structural precedent. This ADR has smaller scope: single CHECK extension + data UPDATE for 3 MT rows; no new tables, columns, or indexes.

## Alternatives Considered

- **Keep `'other_overlay'` for V1, revisit at V2.** MT V1's posture; rejected because CO would otherwise ship 10 more imprecisely-bound rows, compounding the migration cost when it lands.
- **Sibling boolean `is_no_hunt`.** Rejected: redundant truth source (`role='restricted_area' AND is_no_hunt=true` would mean the same as `role='no_hunt_zone'`), violates ADR-010's enum-not-flag, harder to consume.
- **Reuse `'restricted_area'`.** Rejected: `'restricted_area'` already means internal HD restrictions (per `EXPECTED_RA_ORPHAN_IDS` and handoff §8 #4's MT V1 split). Collapsing loses encoded information.
- **One-role-per-binding (unstated invariant, made explicit).** A `jurisdiction_binding` is a `(record, geometry, role)` triple; conjunctive semantics (CWD zone inside an NP — flagged for M2 by the research doc) are expressed by writing TWO bindings with two roles, not a multi-role field. Each `(record, geometry)` pair can carry multiple bindings, each with one role.
- **PAD-US `Pub_Access` vocabulary or `federal_protected_area`.** Chose `no_hunt_zone` over PAD-US codedValues (`Pub_Access='RA'` is "restricted access," not "no hunting" per the research doc) and over `federal_protected_area` because state-level no-hunt zones (state preserves) may need the same role in M3+.

## Consequences

### Positive

- `check_land_status` can return semantically precise "no hunting allowed," distinct from "rule restricts your weapon."
- ADR-010's `role`-as-relationship discipline strengthened; `'other_overlay'` scope narrowed.
- CO S05.4 unblocks and ships 10 PAD-US-sourced no-hunt zones bound as `role='no_hunt_zone'`.
- Future western states inherit the pattern for federal no-hunt overlays without additional schema work.

### Negative

- **Five-place sync required**, compounding ADR-005's three-place-schema cost. Sites:
  - `supabase/migrations/<timestamp>_jurisdiction_binding_no_hunt_zone_role.sql` (new DDL CHECK migration)
  - `ingestion/ingestion/lib/schema.py` (Pydantic `GeometryRole` Literal)
  - `mcp-server/src/types/schema.ts` (TypeScript `GeometryRole` union)
  - `docs/architecture.md` §"Schema types"
  - `ingestion/ingestion/lib/overlays.py` (`GeometryRoleForE03` Literal alias — the state-agnostic-shared 5th surface; failure to update produces mypy/Literal mismatch)
- **Data migration for 3 MT rows.** Binding ids derive from `EXPECTED_RA_ORPHAN_IDS` in `ingestion/states/montana/build_overlay_fixture.py:236-242`:
  - `MT-restricted-bigame-glacier-national-park-geom`
  - `MT-restricted-bigame-sun-river-game-preserve-geom`
  - `MT-restricted-bigame-yellowstone-national-park-geom`
- **Test + code touch-up.** `test_load_jurisdiction_bindings.py` locks `role='other_overlay'` at 4 sites (`:1025` set-equality; `:1053` `test_role_is_other_overlay_only` + `:1064` per-binding; `:1896-1898` `_valid_roles` frozenset). `load_jurisdiction_bindings.py:599-608` docstring asserts the V1 invariant; `:637` hardcodes the role Literal. All revise in the migration story.

### Neutral

- `'other_overlay'` remains valid for legitimately-residual cases; scope narrowed, not deprecated.
- `'restricted_area'` continues to mean internal HD weapon/season restrictions (MT V1 split preserved).
- E06 will surface `verbatim_rule` text for each CO no-hunt zone from the CPW Big Game brochure; the `role` value is the binding-side decision, not the text-provenance decision.

## Links

- [ADR-002](ADR-002-mcp-canonical-interface.md) — `check_land_status` MCP tool; the semantic-precision argument
- [ADR-006](ADR-006-schema-versioned-from-day-one.md) — three-place sync discipline
- [ADR-010](ADR-010-decomposed-entity-model.md) — enum-not-flag and role-as-regulatory-relationship
- [ADR-018](ADR-018-e03-schema-additions.md) — closest structural precedent (schema-extending ADR with migration + sync)
- [`docs/research/colorado-restricted-areas-evaluation.md`](../research/colorado-restricted-areas-evaluation.md) — empirical PAD-US evidence; 10 V1-scoped CO no-hunt zones
- [`docs/planning/handoffs/M1-to-M2-handoff.md`](../planning/handoffs/M1-to-M2-handoff.md) §8 #4 — M1 carry-forward signaling this ADR
- [`docs/planning/epics/E05-colorado-geometry-ingestion.md`](../planning/epics/E05-colorado-geometry-ingestion.md) §S05.4 — consuming story
- [`supabase/migrations/20260425000000_initial_schema.sql`](../../supabase/migrations/20260425000000_initial_schema.sql) — current 7-value role CHECK constraint
- [`ingestion/states/montana/load_jurisdiction_bindings.py`](../../ingestion/states/montana/load_jurisdiction_bindings.py) — MT V1 disposition (3 no-hunt zones bound as `other_overlay`)
