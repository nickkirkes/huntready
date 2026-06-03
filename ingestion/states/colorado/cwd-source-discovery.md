# CWD Source Discovery — Colorado

## Investigation Date
2026-06-03

## Decision

**CPW publishes no CWD-zone geometry.** All three investigation paths (plus the pre-recorded dead branch (c)) returned NO. Colorado does not define discrete, mapped Chronic Wasting Disease management *zones* the way Montana does — CWD in Colorado is managed at the **Game Management Unit (GMU) / hunt-code** level, not as polygon boundaries.

Consequently, **S05.3 closes with zero `geometry` rows written, no loader created (`load_cwd_zones.py` is NOT added), and `sources.yaml` is NOT extended** (there is no CWD source to register). This is the documented-gap outcome, analogous to S05.4's outcome (b) and to S02.6's zero-row CWD precedent that the S05.5 overlay-fixture invariants already tolerate (E05 epic, S05.5 "Depends on" note: "the latter two may produce zero rows; coverage invariant tolerates this per S02.6's CWD precedent"). Downstream S05.5 and S05.7 are unaffected — their `cwd_zone` coverage assertions are universal quantifiers over an empty set and pass vacuously.

This finding is **material evidence for open question Q18** (see § "Q18 finding" below): it confirms the license/unit-keyed CWD model is the general pattern, not a Montana quirk.

---

## Investigation Tree (per E05 epic S05.3 spec, lines 269–273)

### Path 1 — CPWAdminData service-root catalog scan → **NO**

- **Date queried:** 2026-06-03
- **URL:** `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer?f=json`
- **HTTP status:** 200
- **Layers scanned for `cwd|chronic|disease|wasting` (case-insensitive):** all 30 — **zero matches.**

Full layer inventory (id | name):

| id | name | CWD? |
|----|------|------|
| 0 | CPW Facilities | No |
| 1 | CPW State Park Roads - Public | No |
| 2 | CPW Trail Segments | No |
| 3 | CPW Gold Medal Streams | No |
| 4 | CPW Gold Medal Lakes | No |
| 5 | CPW Managed Properties (public access only) | No |
| 6 | CPW GMU Boundary (Big Game) | No (the S05.2 GMU layer) |
| 7 | CPW GMU Boundary (Bighorn Sheep) | No |
| 8 | CPW GMU Boundary (Mtn Goat) | No |
| 9 | CPW District Boundary | No |
| 10 | CPW Area Boundary | No |
| 11 | CPW Region Boundary | No |
| 12 | CPW Walk In Access Program | No |
| 13 | CPW All Properties Centroid | No |
| 14 | COTREX Trailheads | No |
| 15 | COTREX Trails | No |
| 16 | CPW Aquatic Native Species Conservation Waters | No |
| 17 | CPW Aquatic Sportfish Management Waters | No |
| 18 | CPW Aquatic Cutthroat Trout Designated Crucial Habitat | No |
| 19 | CPW Aquatic Gold Medal Waters | No |
| 20 | DAU Boundary (Bear) | No |
| 21 | DAU Boundary (Bighorn Sheep) | No |
| 22 | DAU Boundary (Deer) | No |
| 23 | DAU Boundary (Elk) | No |
| 24 | DAU Boundary (Lion) | No |
| 25 | DAU Boundary (Moose) | No |
| 26 | DAU Boundary (Mtn Goat) | No |
| 27 | DAU Boundary (Pronghorn) | No |
| 28 | CPW Offices | No |
| 29 | CPW Fee Title Parcels | No |

**Decision:** CPWAdminData carries no CWD-zone layer as a sibling to layer 6. The DAU (Data Analysis Unit) boundaries are species-keyed herd-management units, not CWD zones.

### Path 2 — ArcGIS Online Hub / CPW organization scan → **NO**

- **Date queried:** 2026-06-03
- **CPW org id (services5.arcgis.com):** `ttNGmDvKQA7oeDQ3`

| # | Query | Result |
|---|-------|--------|
| 1 | `arcgis.com/sharing/rest/search?q=(CWD OR chronic wasting) orgid:ttNGmDvKQA7oeDQ3` | **Total: 0** — no CWD content owned by CPW |
| 2 | Full hosted-service listing: `services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services?f=json` (~200 services) scanned for `cwd\|chronic\|disease\|wasting\|sampl\|health` | Only near-misses: `CPW_ANS_Sampling_2018`, `CPW_ANS_Sampling_2019`, `CPW_SamplingData_2017` (ANS = **Aquatic Nuisance Species**, unrelated) and `CPWHPH*` (not CWD). **No CWD/chronic/disease/wasting service exists.** |
| 3 | `arcgis.com/sharing/rest/search?q="chronic wasting" Colorado` (broad public) | 18 hits, **all third-party** — USGS StoryMaps, academic (West Point USMA "Colorado_Wyoming CWD Prevalence 2021", UW-Madison), other-state DNRs. None CPW-authoritative; none a regulatory zone boundary. |

**Decision:** Unlike Montana — whose Path 2 surfaced the authoritative MtFishWildlifeParks-owned `ADMBND_HD_CWD` Feature Service (item `8837c07298054f5e8be2e072681d870c`) with discrete Libby + Kalispell zone polygons — CPW does not publish any CWD geometry on ArcGIS Online under its organization account.

### Path 3 — PDF hand-trace fallback → **nothing polygonal to trace (rejected per ADR-001)**

CPW manages CWD by **hunt code / GMU**, not by mapped zone polygons:

- CPW's CWD page confirms 2026 management is hunt-code-driven: **no mandatory deer CWD testing**; **mandatory elk** test-sample submission from **specific rifle hunt codes** (enumerated on pp. 41–52 of the 2026 Big Game Brochure). This is CPW's 15-year Colorado Chronic Wasting Disease Response Plan, which *rotates mandatory testing of hunt codes around the state* — units, not boundaries.
- USGS's North American CWD distribution map "changed from displaying positive detections by county to positive detections **by wildlife management unit** for Colorado, to better align with how the state publicly reports positive CWD detections" — corroborating that Colorado's CWD reporting unit is the management unit (GMU), not a discrete zone polygon.

There is therefore no authoritative CWD-zone *boundary* published by CPW to hand-trace. Tracing a polygon from a prevalence/monitoring map (which depicts surveillance data, not a regulatory hunt zone) would invent a boundary CPW does not publish — an **ADR-001 ("authority preserved, not replaced / no invented data") violation**. Path 3 is rejected.

### Path (c) — GMU-layer attribute filter → **NO (pre-recorded dead branch)**

Pre-recorded NO per the E05 epic (S05.3 Context) and the ArcGIS Fidelity SHOULD-FIX: CPW GMU layer 6 carries species-keyed DAU fields (`GMUID`, `COUNTY`, species-DAU fields, `EDIT_DATE`, `INPUT_DATE`, etc.) — no CWD-flag attribute to filter on. Confirmed: no CWD-keyed attribute exists on the GMU layer.

---

## Contrast with Montana (S02.5)

| | Montana (S02.5) | Colorado (S05.3) |
|---|---|---|
| CWD geometry published? | **Yes** — dedicated `ADMBND_HD_CWD` FeatureServer | **No** — no layer, no service, no polygon |
| Authoritative source | MtFishWildlifeParks ArcGIS Online item `8837…` | None exists |
| V1 rows ingested | 2 zones (Libby, Kalispell) | 0 |
| CWD management model | Discrete CWD Management Hunt Areas (polygons) **plus** per-license sampling sentences | Hunt-code / GMU-keyed mandatory submission; no zones |
| Loader | `montana/load_cwd_zones.py` | none (not created) |

Montana already showed the CWD sampling *mandate* is license-keyed (Q18's core observation: HD 103's `Deer Permit: 103-50` carries the sampling rule but sits outside the Libby zone overlap). Colorado removes even the zone-geometry leg of the model — its CWD obligations are entirely unit/hunt-code-keyed.

---

## Q18 finding (PM surface to human)

**Q18** (`docs/open-questions.md`): *"Does `reporting_obligation` model per-zone CWD sampling rules in V1?"* — V1 verdict (line 372): ship 0 CWD-sampling `reporting_obligation` rows; text searchable via `regulation_record.additional_rules`. Named trigger to revisit (line 376): *"Second CWD-state lands (Colorado) — confirms whether license-keyed vs. zone-keyed is a Montana quirk or a general pattern."*

**The CO finding resolves that trigger:** Colorado is the second CWD state, and it has **no CWD zone polygons at all** — CWD obligations are attached to hunt codes / GMUs. Zone-keyed binding is not merely awkward for Colorado, it is **structurally impossible** (there is no zone to key on). This is strong empirical confirmation that the **license/unit-keyed model is the general pattern**, not a Montana quirk.

**PM recommendation (E06 retains the final call):** E06 should retain Q18's V1 license-keyed disposition — CWD sampling rules continue to live in `regulation_record.additional_rules`, keyed by the GMU/hunt-code-anchored regulation_record, with **0** typed `reporting_obligation` rows for CWD. There is no zone-keyed alternative available for Colorado. **S05.3 only documents the geometry gap; the Q18 decision is E06's** and is flagged to the human here BEFORE E06's reporting-obligation loader specs are drafted, per the S05.3 AC.

---

## Source URLs (verified 2026-06-03)

- CPWAdminData FeatureServer root: `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services/CPWAdminData/FeatureServer?f=json` (HTTP 200; 30 layers, no CWD)
- CPW org hosted-service listing: `https://services5.arcgis.com/ttNGmDvKQA7oeDQ3/ArcGIS/rest/services?f=json` (HTTP 200; ~200 services, no CWD)
- CPW Chronic Wasting Disease page: `https://cpw.state.co.us/activities/hunting/big-game/chronic-wasting-disease`
- USGS — Expanding Distribution of Chronic Wasting Disease: `https://www.usgs.gov/centers/nwhc/science/expanding-distribution-chronic-wasting-disease`

---

## UAT disposition

The S05.3 spec UAT criterion (E05 epic, S05.3 AC: "UAT — named zones resolve correctly via `ST_Covers`") calls for an `extensions.ST_Covers` spot-check of ≥2 named CWD zones (positive inside-point + negative outside-control). **This is N/A — no CWD zones exist to query.** UAT is satisfied instead by this documented-gap investigation report and the Q18 surface to the human. No spatial query is possible or meaningful against zero rows; the honest verification is the completeness of the three-path investigation recorded above.

---

## Initial Load Record

- **Date:** 2026-06-03
- **Loader:** none — no CWD source exists to ingest
- **Rows written:** 0
- **`sources.yaml` extended:** no (no CWD source to register)
- **Result:** documented gap; CPW publishes no CWD-zone geometry; CWD is hunt-code/GMU-keyed in Colorado.
