# Draw Mechanics Deferrals (Q12)

This file tracks deferrals related to the `parameters` escape-hatch field on `draw_spec` (Q12 from the E03 epic, per PRD 001 §"Out of scope"). If extraction during E03 surfaces a draw mechanic that cannot be expressed within the structured `draw_spec` fields and appears to require `parameters`, the implementer flags it here per the operational definition in this directory's README.

Per E03 epic line 32: do not exercise the `parameters` field during E03. Flag-and-defer to this file for M2 handoff.

---

## Items

<!-- S03.7+ implementers: append entries here when a draw mechanic requires deferral.
     Format: ### <hunt_code or pattern> — brief description
     Include: source span, which structured field(s) were insufficient, why parameters was tempting. -->
