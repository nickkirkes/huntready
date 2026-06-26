# M3 Source-of-Truth Updates — Tracking Checklist (ARCHIVED)

**Created:** 2026-06-24
**Completed:** 2026-06-24
**Disposition:** ARCHIVED — all updates landed and committed on branch `docs/m3-planning` (branched off `feat/S06.8.0-draw-mechanics-extraction`), per user direction; the unrelated in-flight E06/S06.8 work on that feature branch was deliberately left out of the commit. (An earlier draft of this line said the commit was on `feat/S06.8.0-draw-mechanics-extraction` directly — that reflected the original plan before the user pivoted to a dedicated `docs/m3-planning` branch; corrected here for accurate provenance.) Retained for historical context per the documentation-as-handoff discipline (ADR-009).
**Purpose:** Tracked the source-of-truth document changes PRD 003 (`docs/planning/prds/003-M3-canonical-interface.md`) implied, so they landed coherently and with human authorization. Authorized by the user on 2026-06-24 during the M3 planning session (the remote-MCP-on-Cloudflare posture sign-off and its downstream reconciliations).

---

## 1. `docs/roadmap.md`

- [x] **M3 section rewrite** — evolved "Canonical interface live" to the remote posture (remote Streamable HTTP, Cloudflare Workers, deployed-in-M3, OAuth-2.1-ready minimal auth seam, `mcp-remote` local dev); Signals + Deliverables + Exit criteria updated. Posture-evolution note added referencing PRD 003.
- [x] **M3→M4 dependency note** — M4 now inherits a deployed server.
- [x] **M4 section reconciliation** — the M4 "MCP server HTTP shim deployed to Fly.io/Railway" signal + deliverable updated; M4 deploys only the web companion.

## 2. `docs/open-questions.md`

- [x] **Q5 → RESOLVED: no BFF** (in place; cites ADR-023 + architecture addendum; CORS-is-M3 consequence noted).
- [x] **Q6 → RESOLVED: Cloudflare Workers** (in place; notes Workers was outside the original option set).
- [x] **Q21 → RESOLVED: option (a), implemented in E07** (in place; no separate ADR).
- [x] **New Q22: production auth model** added (deferred; trigger = production go-decision / post-OnX).
- [x] **Q14 note** — serving read connection adopts current key format in E08; RLS-runbook half stays open.

## 3. `docs/adrs/` — new ADRs (Proposed pre-implementation)

- [x] **ADR-023 — Remote Authenticated MCP Server Posture** (Proposed; mcp, deployment; resolves Q5/Q6).
- [x] **ADR-024 — Edge-Runtime Postgres Access for the Serving Stack** (Proposed; storage, mcp; refines ADR-003).
- [x] **ADR-003 status note** — added, pointing to ADR-024.
- [x] **`docs/adrs/README.md` index** — rows for ADR-023, ADR-024 added.

## 4. `docs/architecture.md`

- [x] **Serving-posture addendum** — transport, Workers, edge Postgres, no-BFF.
- [x] **`check_land_status` V1 contract note** — narrowed to loaded overlays; fuller PAD-US/BLM-PLAD framing flagged as eventual contract.

## 5. `CLAUDE.md`

- [x] **ADR list** — count 22 → 24; ADR-023, ADR-024 bullets added. (M2/E06 project-status preamble deliberately untouched.)

## 6. `docs/planning/prds/003-M3-canonical-interface.md`

- [x] **Header "New ADRs"** — reconciled to ADR-023 (posture + auth seam) + ADR-024 (edge Postgres); auth folded into ADR-023; ADR-002 link path fix also applied during the review pass.

## 7. Verification + close-out

- [x] All new/changed internal links resolve (ADR-023/024 filenames verified present; relative paths checked).
- [x] ADR index, CLAUDE.md ADR list, and architecture.md mutually consistent on ADR-023/024.
- [x] open-questions.md no longer lists Q5/Q6/Q21 as open (RESOLVED in place); Q22 present.
- [x] Committed on `docs/m3-planning` (branched off `feat/S06.8.0-draw-mechanics-extraction`); M3 files only; unrelated in-flight E06/S06.8 work left uncommitted.
- [x] Archived to `docs/planning/archive/`.
