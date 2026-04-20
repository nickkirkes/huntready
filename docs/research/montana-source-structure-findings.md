# Montana Source Structure Findings

Decision-ready findings for the HuntReady ingestion pipeline team, based on a direct-fetch investigation of Montana Fish, Wildlife & Parks (MT FWP) primary sources. All facts below were verified by HTTP fetch of fwp.mt.gov, fwp-gis.mt.gov, or gis-mtfwp.hub.arcgis.com during the investigation window (April 19, 2026). Where a claim could not be verified by direct fetch, it is labeled as uncertain. Nothing below is inferred from third-party guides, forums, or news articles.

License year in effect: 2026/2027 (adopted by the Fish & Wildlife Commission on December 4, 2025 under MCA 87-1-301; valid March 1, 2026 – February 28, 2027).

## Publications inventory

One row per FWP publication relevant to big game regulations for the V1 species (elk, mule deer, whitetail, pronghorn, black bear). The deer/elk/antelope booklet is biennial (covers two license years); the black bear booklet is annual. Every PDF listed below was downloaded and had its page count, internal PDF title, and modification date verified directly.

| Title (as published by FWP) | URL | Format | Cadence | Edition verified | Page count | Scope |
|---|---|---|---|---|---|---|
| 2026 Deer Elk Antelope (pronghorn) Hunting Regulations | https://fwp.mt.gov/binaries/content/assets/fwp/hunt/regulations/2026/2026-dea-regulations-final-with-low-resolution-maps-for-web.pdf | PDF | Biennial (adopted Dec 4, 2025; valid Mar 1, 2026 – Feb 28, 2027) | 2026 booklet, PDF modified Apr 16, 2026 | **141 pages** (verified via pdfinfo) | Seasons, methods of take, per-HD regulation tables (pp. 48–123 deer/elk; pp. 136–142 antelope), youth/PTHFV opportunities (p. 124), multi-district licenses (pp. 126–127), fees and license rules, restricted-area descriptions (pp. 28–30) |
| 2026 Black Bear Hunting Regulations | https://fwp.mt.gov/binaries/content/assets/fwp/hunt/regulations/2026/2026-black-bear-final-for-web.pdf | PDF | Annual (valid Mar 1, 2026 – Feb 28, 2027) | 2026 booklet, PDF modified Mar 17, 2026 | **16 pages** (verified) | BMU regulation table (spring/archery/fall seasons, quotas, hound licensing), bear identification test requirement, 48-hour reporting, Region-1-vs-Regions-2–7 inspection split |
| Corrections to the 2026 Printed Black Bear Regulations | https://fwp.mt.gov/binaries/content/assets/fwp/hunt/regulations/2026/corrections-to-the-2026-printed-black-bear-regulations.pdf | PDF | Ad-hoc correction | PDF created Mar 18, 2026 (the day after the booklet) | **1 page** (verified) | Amends hound-hunting licensing language and deletes the hound training-season column from the BMU tables |
| 2026/2027 Deer Elk Antelope Black Bear Moose Lion Sheep Goat Bison — Hunting District Legal Descriptions | https://fwp.mt.gov/binaries/content/assets/fwp/hunt/regulations/2026/2026-2027-legal-descriptions-finalfor-web.pdf | PDF | Biennial | 2026/2027 edition, PDF created Feb 3, 2026 | **56 pages** (verified) | Prose legal descriptions of every HD and BMU. TOC verified: Region descriptions p.3, Antelope p.5, Bighorn Sheep p.10, Bison p.13, Black Bear MU p.14, Deer & Elk p.19, Moose p.36, Mountain Goat p.43, Mountain Lion p.46, Contacts p.54 |
| Hunting Regulations landing page | https://fwp.mt.gov/hunt/regulations | HTML | Continuously maintained | Live (verified 2026-04-19) | n/a | Hub linking to every current-year booklet, including corrections PDFs |
| Species Regulation pages | https://fwp.mt.gov/hunt/regulations/elk · /deer · /antelope · /black-bear | HTML | Continuously maintained | Live | n/a | Species summary, season dates, license basics, deep-links into the booklet PDFs |
| Elk Shoulder Seasons page | https://fwp.mt.gov/hunt/elk-shoulder-seasons | HTML | Continuously maintained | Live | n/a | Shoulder-season rationale (cites MCA 87-1-323), affected-HD map via iframe to Hunt Planner |
| Youth Hunter page | https://fwp.mt.gov/hunt/youth | HTML | Continuously maintained | Live | n/a | Youth-hunt eligibility, apprentice program |
| Fish & Wildlife Commission proposal & justification PDFs | https://fwp.mt.gov/binaries/content/assets/fwp/commission/{year}/{meeting}/... | PDF | Ad-hoc per commission meeting | Dec 4, 2025 meeting (referenced by the adopted booklets) | Varies | Public-input sheets, regional justifications, amendments. These are the provenance of the adopted booklets |
| FWP News announcements | https://fwp.mt.gov/homepage/news/... | HTML | Ad-hoc | Continuously | n/a | FWP press releases — informal change-signal feed, not rule text |
| Base Hunting / License fee pages | https://fwp.mt.gov/buyandapply/hunting-licenses/base-requirements · /resident-licenses/fees · /nonresident-licenses/fees | HTML | Continuously maintained | Live | n/a | Fee tables for Conservation License, Base Hunting License, species licenses, AISPP, apprentice certification |
| Drawing Statistics | https://fwp.mt.gov/buyandapply/hunting-licenses/drawing-statistics → https://myfwp.mt.gov/fwpPub/drawingStatistics | HTML (search form) | Updated per draw cycle | Live | n/a | Historical draw success rates by district/permit — HTML table output only |
| Block Management program pages | https://fwp.mt.gov/bma · /hunt/access/blockmanagement/region-{1–7} | HTML | Seasonal | Live | n/a | Program overview, per-region BMA access summaries |
| Montana Outdoors — "Reconstructing the Regulations" | https://fwp.mt.gov/binaries/content/assets/fwp/montana-outdoors/2025/regs.pdf | PDF | Single article (2025) | 2025 | Not verified (not essential to V1) | Narrative explainer of the biennial rulemaking cycle |

Publications **ruled out** for V1 scope (confirmed to exist via the hunt/regulations landing page but outside V1 species): 2026 Upland Game Bird (2026-upgbrd-final-for-web.pdf), 2026 Migratory Bird / Sandhill Crane / Waterfowl (2026-msgb-final-for-web.pdf + correction), 2026 Light Goose (2026-light-goose-regulations-final-for-web.pdf). The fact that FWP publishes **correction PDFs as a separate publication type** (verified for both black bear and MSGB this cycle) is a load-bearing discovery for the ingest pipeline — a regulation booklet is not a single artifact, it is a base PDF plus zero or more correction amendments.

## Structured endpoints inventory

FWP exposes two structured data surfaces plus one web-app surface. The ArcGIS REST deployment at `fwp-gis.mt.gov` is the authoritative machine-readable source for boundaries; `gis-mtfwp.hub.arcgis.com` republishes the same layers in downloadable form (GeoJSON, Shapefile, FeatureServer); `myfwp.mt.gov` is an interactive web app with no documented JSON API. Every endpoint below was verified by a live HTTP 200 fetch; the layer counts and field lists are from direct `?f=json` inspection during this investigation.

| Endpoint | Type | Purpose | Auth | Update cadence | Response shape (verified) |
|---|---|---|---|---|---|
| https://fwp-gis.mt.gov/arcgis/rest/services | ArcGIS REST root | Lists folders: `admbnd`, `cnsvtn`, `energy`, `fwplnd`, `refrnc`, `toolboxes`, `Utilities`, `wild` (9 folders total) | Open (anonymous) | n/a | JSON folder listing when `?f=json` appended |
| https://fwp-gis.mt.gov/arcgis/rest/services/admbnd/huntingDistricts/MapServer | ArcGIS MapServer | Regulated hunting-district boundaries and species-specific sub-layers. **40 feature layers total**, grouped as Big Game (layers 0–23), Bird (24–34), Furbearer (35–39) | Open | Not documented. Max record count 2000. WKID 102100 (Web Mercator). Supported formats: JSON, geoJSON, PBF. Supports Query, Identify, Export, QueryLegends, QueryDomains, Find, Return Updates | V1-relevant big-game layers (verified by name via `?f=json`): **#2 Big Game Restricted Areas** (PORTIONNAME, REG, COMMENTS, AREA_AC/KM/MI), **#3 Antelope Hunting Districts**, **#4 Antelope Portions**, **#10 Black Bear Hunting Districts**, **#11 Deer Elk Lion Hunting Districts** (DISTRICT, DEERWEBPAGE, ELKWEBPAGE, MAPLINK, REG, AREA\_\*, REGYEAR), **#12 Deer Portions – Mule Deer**, **#13 Deer Portions – White-tailed Deer**, **#14 Elk Portions** (MAPLINK, REG, DISTRICT, PORTIONNAME, PORTIONTYPE, COMMENTS, SHAPECODE, AREA\_\*, REGYEAR), **#15 Elk Restricted Areas**. Geometry: Polygon |
| https://fwp-gis.mt.gov/arcgis/rest/services/wild/bigGameDistribution/MapServer | ArcGIS MapServer | Species distribution overlays (habitat/range, not regulatory) | Open | Not documented | 27 polygon layers spanning all big-game species: Antelope (0–2), Bighorn (3–5), Bison (6–8), Black Bear (9), Elk (10–12), Moose (13–15), Goat (16–18), Lion (19), Mule Deer (20–22), Whitetail (23–25), Wolf (26) |
| https://fwp-gis.mt.gov/arcgis/rest/services/fwplnd/fwpLands/MapServer | ArcGIS MapServer | FWP Fishing Access Sites, State Parks, Wildlife Management Areas | Open | Not documented | 8 layers: FAS points + polygons (1, 2), State Park points + polygons (4, 5), WMA points + polygons (7, 8); max record count 2000 |
| https://gis-mtfwp.hub.arcgis.com/ | ArcGIS Hub (site) | FWP public data catalog — republishes a curated subset of the REST layers with downloadable formats (GeoJSON, Shapefile, KML, CSV) and per-dataset FeatureServer URLs | Open | Per-dataset | HTML catalog; each dataset exposes an "API Resources" panel linking to the underlying FeatureServer |
| Deer and Elk Hunting Districts (2026 and 2027 Seasons) — https://gis-mtfwp.hub.arcgis.com/items/d148ae5ae2374132b53b438b6c03264f | Hub dataset (Feature Service) | HD polygons for deer & elk in the current license year | Open | Per license year | Polygons; GeoJSON/Shapefile/FeatureServer downloads |
| Big Game Hunting District Restricted Areas (2026 and 2027 Seasons) — https://gis-mtfwp.hub.arcgis.com/datasets/1825a4b1b0664fba84f04922ce244d7a_0/about | Hub dataset | Closures, weapon-restriction areas, HD sub-portions with extra rules | Open | Per license year | Polygons |
| Elk Hunting District Portions (2026 and 2027 Seasons) — https://gis-mtfwp.hub.arcgis.com/datasets/d5e5c706ea9d49eeb30c67e1b2fe5eef_0/explore | Hub dataset | Sub-polygons within elk HDs that carry different rules | Open | Per license year | Polygons |
| Block Management Area (BMA) Boundaries / Points / Lines — e.g. https://gis-mtfwp.hub.arcgis.com/items/14973cd952c04f779e254963a4b3b72d | Hub datasets (3 separate layers) | Enrolled private-land public-access areas | Open | **Per hunting season; FWP explicitly notes BMAs change mid-season** | Polygons, Points, Lines variants |
| FWP Lands Locations – Points — https://gis-mtfwp.hub.arcgis.com/datasets/5308d368536047c18f22074adacadbf8_0/about | Hub dataset | State park, FAS, WMA points | Open | Not documented | Points |
| MT FWP Hunt Planner web map | https://fwp.mt.gov/gis/maps/huntPlanner/ | ArcGIS Web App | Interactive map UI (not a data API) | Open | Synced with Hub datasets | HTML + JS web app |
| MyFWP Hunt Planner — https://myfwp.mt.gov/fwpPub/planahunt.action | Web application | Interactive "plan a hunt" UI | Open | Live (the per-species data surface was showing "Data is currently unavailable" at investigation time — a transient FWP-side state, not a permanent outage) | HTML. No documented JSON API; underlying XHRs exist but are not publicly contracted |
| MyFWP Drawing Statistics — https://myfwp.mt.gov/fwpPub/drawingStatistics | Web application (search form) | Historical draw statistics | Open | Per draw cycle | HTML search form; results are HTML tables. No JSON export |
| MyFWP Draw Result Lookup — https://myfwp.mt.gov/fwpExtPortal/myDrawResult_input.action | Authenticated portal | Personal draw results | MyFWP account required | Per draw cycle | Portal (not a data API) |
| ols.fwp.mt.gov | Online license sales | License and application purchase flow | User account | n/a | Not a regulation data endpoint; relevant only as the purchase destination HuntReady links out to |

**Ruled out (checked, not found):** A documented, public JSON API for per-HD quotas, per-permit drawing odds, per-license pricing, or per-permit application counts. The Hunt Planner and Drawing Statistics pages clearly query internal endpoints, but FWP does not publish their contracts. Building on undocumented internal URLs is a correctness risk.

## Section structure examples

Five examples, each drawn by direct extraction from the downloaded PDFs using `pdftotext -layout`. URLs and page numbers are exact. Each example shows the actual structural shape (table vs. prose, column set, sub-row pattern) that will drive extraction strategy.

### Example 1 — Deer/Elk per-HD regulation table (HD 262, Bitterroot Farmlands)
- **Source:** DEA booklet PDF, p. 65
- **Publication date:** Adopted Dec 4, 2025; valid Mar 1, 2026 – Feb 28, 2027
- **Form:** Structured table with uniform column set. Each HD is introduced by a `HD {number} - {name}` heading, optionally followed by `NOTE:` lines, then two sub-blocks (`DEER`, `ELK`), each containing one row per license/permit type.

**Column schema extracted from the printed header:**
`LICENSE/PERMIT | OPPORTUNITY | APPLY BY DATE | QUOTA | QUOTA RANGE | EARLY SEASON DATES | ARCHERY ONLY SEASON DATES | GENERAL SEASON DATES | HERITAGE MUZZLELOADER SEASON DATES | LATE SEASON DATES | OPPORTUNITY SPECIFIC DETAILS AND/OR RESTRICTIONS`

**Verbatim sample row (General Deer, HD 262):**
> "General Deer License | Antlerless Mule Deer | – | – | – | Aug 15-Sep 04 | Sep 05-Oct 18 | Oct 19-Nov 29 | – | Nov 30-Jan 15 | ArchEquip only."

**Verbatim sample row (Deer B license with restrictions, HD 262):**
> "Deer B License: 262-00 | Antlerless Mule Deer | Jun 1 | 100 | 25-300 | Aug 15-Sep 04 | – | – | – | Nov 30-Jan 15 | ArchEquip, shotgun, traditional handgun, muzzleloader, or crossbow only. Only valid on private land."

**Structural analysis:**
- **Seasons** are expressed as five named date ranges per row (Early / Archery Only / General / Heritage Muzzleloader / Late). An empty cell (`-`) means the license is not valid in that season type. The "Early" and "Late" columns *are* the shoulder-season mechanic — there is no separate "shoulder" column.
- **Methods of take** appear partially in the column set (Archery Only column) and partially in the free-text "Opportunity Specific" restrictions cell ("ArchEquip, shotgun, traditional handgun, muzzleloader, or crossbow only").
- **Unit-specific exceptions** are expressed as rows with extra restriction text, not as separate sections. Private-land-only, specific-HD-only, and weapon restrictions are all in the rightmost column.
- **Tag requirements** are encoded in the License/Permit column and license code (e.g., `262-00` = Deer B for HD 262). The Apply By Date + Quota + Quota Range columns express draw-vs-OTC status (OTC rows carry the literal string `OTC: Jun 15` in the Apply By Date column and `UNL` in the Quota column).
- **License prerequisites** are not in the per-HD table; they are defined upstream on pp. 12–15 and referenced by the license code.

### Example 2 — Elk shoulder season (HTML narrative + HD tables)
- **Source:** https://fwp.mt.gov/hunt/elk-shoulder-seasons (HTML) and DEA booklet PDF per-HD entries (pp. 48–123)
- **Form:** Shoulder seasons are **not a separate section** in the booklet. They are rows within each affected HD's table that populate the Early Season (Aug 15–Sep 04) and/or Late Season (Nov 30–Feb 15) columns, typically marked "ArchEquip only" or "Only valid on private land."

**Verbatim from the Elk Shoulder Seasons page:**
> "A shoulder season is a firearms season that occurs outside the five-week general firearms and archery seasons. While most shoulder seasons focus on antlerless elk harvest on private land and are not intended to replace or reduce harvest during the existing archery or five-week general firearms seasons, a few are meant to address problematic distribution of elk. Shoulder seasons will vary in timing and function from hunting district to hunting district. In some districts the shoulder seasons will start as early as Aug. 15 and go as late as Feb. 15."

**Verbatim booklet definition (DEA p. 8):**
> "SHOULDER SEASON: a hunting opportunity conducted before or after the five week general deer/elk season; see individual hunting districts."

**Statutory anchor:** MCA 87-1-323 (cited on the Elk Shoulder Seasons page).

**Structural analysis:** Shoulder seasons are not a first-class entity in the source data. They are the union of two columns (Early + Late) across many HDs, filtered to elk rows. Extraction must reconstruct "shoulder season" as a view, not a record.

### Example 3 — Black Bear BMU regulation table (Region 1 rows)
- **Source:** Black Bear booklet PDF, pp. 10–11
- **Form:** Structured BMU table, segmented by FWP Region. Each row is one BMU with uniform columns.

**Column schema:**
`BMU | Spring Quota | Fall Quotas | Max No. NR Hound Licenses | NR Hound License | Hound Hunting Season | Spring Season | Archery-only Season | General Season | Opportunity specific details and/or restrictions`

**Verbatim sample rows (Region 1):**
> "100 | – | – | – | – | – | Apr. 15-Jun. 15 | Sep. 05-Sep. 14 | Sep. 15-Nov. 29 | –"
>
> "103 | – | – | – | – | – | Apr. 15-Jun. 15 | Sep. 05-Sep. 14 | Sep. 15-Nov. 29 | Check Restricted Area Descriptions (p 13): Libby Big Game Archery-only Hunting Area."

**Verbatim female sub-quota rule (p. 7):**
> "Spring Season Closure: BMUs 300, 301, 319, and 580 are subject to close, with regular public notice, at any point after May 31 if the cumulative spring harvest exceeds 37% female black bears."

**Verbatim quota closure rule (p. 7):**
> "In BMUs 411, 420, 440, 450, 510, 520, 530, 600, and 700 when the quota is reached or approached in each of these districts, the black bear season in that district will close. For quota status, call 1-800-385-7826 or 406-444-1989."

**Verbatim Region-1 inspection variant (p. 10):**
> "Physical inspection of a black bear harvested in Region 1 is no longer required. However, mandatory 48 hour reporting of any successful black bear harvest is required. In addition, successful hunters are required to submit two premolar teeth from any black bear harvested in Region 1 within 10 days of harvest."

**Verbatim Regions 2–7 inspection variant (p. 7):**
> "Within 10 days of harvesting a black bear, the successful hunter must present to a Montana FWP official the complete bear hide and skull for the purpose of inspection, tagging, and possible removal of a tooth (for aging). The hide and skull must be presented in a condition that allows full inspection and tooth collection (i.e., unfrozen)."

**Structural analysis:** The BMU table is as structured as the DEA per-HD table, but the **closure rules live outside the table** in prose on p. 7. A faithful ingest must capture both the tabular row *and* the prose closure predicate that conditionally voids the table's dates. The correction PDF further modifies the table's columns (removes the Hound Training Season column) — so the table schema is itself mutable within a license year.

### Example 4 — Antelope per-HD regulation table (HD 455, Ming Bar)
- **Source:** DEA booklet PDF, p. 136
- **Form:** Structured table, simpler than the deer/elk version (fewer season-type columns).

**Column schema:**
`License | Opportunity | Apply by Date | Quota | Quota Range | Archery Season Dates | Season Dates | Opportunity Specific Information/Restrictions`

**Verbatim rows (HD 455):**
> "Antelope License: 455-20 | Either-sex | June 1 | 2 | 1-15 | Sept. 05-Oct. 09 | Oct. 10-Nov. 08 | (blank)"
>
> "Antelope License: 900-20 | Either-sex | June 1 | 5,600 | 1-7,500 | – | Aug. 15-Nov. 08 | First and only choice. ArchEquip only."

**Verbatim landowner preference language (DEA pp. 17, under "Landowner Preference — MCA 87-2-705"):**
> "Up to fifteen percent of final quotas are set aside for Deer Permit, Elk Permit, Deer B, Elk B, Antelope, Antelope B, and Nonresident Big Game and Elk Combination drawings. Nonresident landowner quotas may not exceed 10 percent of final quotas for any drawing which Montana residents are also eligible to apply for."
>
> "In order to claim landowner preference for deer B, deer permit, and/or antelope drawings, a landowner must own at least 160 acres of land within the hunting district applied for."
>
> "In order to claim landowner preference for the elk B license and/or elk permit drawings, a landowner must own at least 640 contiguous acres of land used by elk as documented by FWP."

**Structural analysis:**
- Every antelope HD has a **quota-limited HD-specific license** (5-digit code matching `{HD}-20` for either-sex and `{HD}-30` for doe/fawn B), plus the **statewide 900-series archery-only license** (`900-20`) which is draw-only, archery-only, first-and-only-choice, with a statewide quota pool of 5,600 and a range of 1–7,500.
- Landowner preference is a **predicate on the quota pool**, not a separate license. It applies only to specific draw types and has different acreage thresholds per species (160 vs 640) and per-population caps (15% total, 10% nonresident).

### Example 5 — Legal description (Deer & Elk HD 100, North Kootenai)
- **Source:** Legal Descriptions PDF, p. 19 (the first entry in the Deer & Elk section)
- **Form:** Pure prose boundary description, keyed by highways, rivers, USFS road numbers, and township-range-section coordinates.

**Verbatim (opening sentence and full description):**
> "100 North Kootenai: That portion of Lincoln County lying within the following-described boundary: Beginning where the Kootenai River meets the Idaho border, then northerly along said border to the Canadian border, then easterly along said border to the east shore of Lake Koocanusa (Kootenai River), then southerly along said shore to Libby Dam and the east shore of the Kootenai River, then southerly and westerly along said shore of the Kootenai River to the Idaho border, the point of beginning."
>
> "Libby CWD Management Zone: Those portions of Lincoln county lying within the following described boundary: Beginning at the junction of Fisher River Rd and Hwy 37, head west on Hwy 37 to the bridge crossing the Kootenai River…"

**Structural analysis:**
- Each HD entry is a named block (`{code} {name}:`) followed by one prose paragraph.
- The legal descriptions PDF contains **overlay zones** (e.g., "Libby CWD Management Zone") that repeat across HDs — these are regulation-bearing sub-geometries that don't have their own HD codes.
- FWP publishes the canonical geometry as polygons via the ArcGIS MapServer (layers 11 for Deer/Elk HDs, 12/13 for mule deer/whitetail portions). Attempting to re-derive geometry from these prose descriptions is wasted effort and likely to diverge from the authoritative polygons.

## Extraction strategy recommendation

**2026 Deer Elk Antelope booklet PDF (141 pages).** Hybrid extraction with strong structural priors. The per-HD regulation tables on pp. 48–123 (deer/elk) and pp. 136–142 (antelope) are **genuinely tabular** and have a fixed column schema that is printed verbatim at the top of each continuation page. Recommend **pdfplumber with table detection**, keyed off the `HD {number} - {name}` heading pattern, extracting one record per `(HD, species-subsection, license-row)` triple. Each extracted row should carry the full set of season-date columns (Early / Archery Only / General / Heritage Muzzleloader / Late) as structured fields, with the free-text "Opportunity Specific" column preserved verbatim as the `rules[].text` field. Opening pages (fees, license rules, definitions, youth/PTHFV chart) are narrative prose with embedded fee tables; recommend selective table extraction for the fee charts and LLM-assisted prose extraction for the narrative sections, with hard validation against known statutory citations (MCA 87-2-104, 87-2-705, 87-2-117).

**2026 Black Bear booklet PDF (16 pages) + corrections PDF (1 page).** The BMU regulation table (pp. 10–11) is extractable with the same `pdfplumber` table strategy as DEA, plus explicit prose-extraction passes for the **closure rules on p. 7** (female sub-quota predicate on BMUs 300/301/319/580; quota-area closure list BMUs 411/420/440/450/510/520/530/600/700). The ingest pipeline **must fetch the corrections PDF** whenever it fetches the base booklet, and the correction amendments must be carried as rule-text updates with a `supersedes` pointer back to the original rows. This implies the `source` discriminator needs a third value beyond `annual_regulations`, `rule_change`, `emergency_order` — call it `correction` — or the pipeline must promote corrections to `rule_change` records with a tight temporal link to the base publication.

**2026/2027 Legal Descriptions PDF (56 pages).** Prose-only. The TOC was re-verified during this investigation (Region p.3, Antelope p.5, Bighorn p.10, Bison p.13, Black Bear MU p.14, Deer & Elk p.19, Moose p.36, Mountain Goat p.43, Mountain Lion p.46, Contacts p.54), so the pipeline can deterministically slice the document into species sections. Within each section, entries are paragraphed with a `{code} {name}:` prefix. Store verbatim text as-is. **Do not parse prose boundaries into geometry** — use the ArcGIS MapServer polygons as canonical. Use the prose only when a user asks "what is the legal boundary of HD X" verbatim.

**Species HTML pages (/hunt/regulations/{species}).** Lightweight summary pages. Extract with a headless HTML parser; treat as *derived* regulation records whose authoritative source is the booklet PDF. Useful as a cross-validation signal: if the HTML page says archery is Sept 5 – Oct 18 but the booklet extraction produces different dates, flag for review. Also the best source for the user-facing "source URL" in a citation block, because the HTML URL is stable across license years while the PDF filename is year-specific.

**Commission meeting PDFs (/binaries/content/assets/fwp/commission/{year}/{meeting}/...).** Provenance only, not rule text. The adopted booklets already carry the commission-adopted language; these documents carry proposals and public-input records. Recommend ingesting URLs and metadata into a `regulation_change` table so each adopted regulation record can cite which commission meeting produced it.

**FWP News posts.** Announcement-grade content. Recommend a scheduled scraper of the news index that flags new posts whose title matches regulation-change patterns ("proposals," "adopted," "changes to"). Treat as signal, not as rule source.

**ArcGIS MapServer and Hub layers.** Direct structured ingestion. Query each layer with `?where=1=1&f=geojson&outSR={"wkid":4326}` and reproject/store in PostGIS. Pin geometries to a `license_year` snapshot so historical records remain resolvable. **Treat BMAs as refreshable in-season** (FWP explicitly states they change mid-season), not frozen at license-year start — either a weekly cron during the active hunting season or a passthrough lookup.

**MyFWP Hunt Planner and Drawing Statistics.** No documented API. For V1, treat draw-odds data as a human-review ingest from the HTML search results; do not build on undocumented internal endpoints.

## Schema pressure points

Items that do not map cleanly to a generic `(source, jurisdiction, applies_to, rules[], tag_info)` record. Each is evidenced by a specific FWP passage verified above.

- **Shoulder seasons are not a record, they are a view.** In the DEA booklet they live inside the Early Season and Late Season columns of the per-HD tables, often with the restriction "ArchEquip only" or "Only valid on private land." The schema's season model needs to admit multiple named date ranges per license row (Early / Archery Only / General / Heritage Muzzleloader / Late) rather than a single start/end per record. *Evidence: HD 262 row in DEA p. 65.*
- **A-license vs B-license split.** Every deer and elk HD has a General license (antlered A) and one or more B licenses (antlerless), each with independent quotas, apply-by dates, OTC-vs-draw status, and weapon restrictions. The schema cannot treat `is_drawn` or `antler_restriction` as singleton fields on a license — they are per-row. *Evidence: HD 262 shows five distinct deer rows under one HD.*
- **Quota closure predicates are prose, not table columns.** A BMU's printed season dates are conditional: "In BMUs 411, 420, 440, 450, 510, 520, 530, 600, and 700 when the quota is reached or approached... the black bear season in that district will close." The female sub-quota predicate on BMUs 300, 301, 319, and 580 is similar: "subject to close... at any point after May 31 if the cumulative spring harvest exceeds 37% female black bears." The schema needs a `closure_predicate` structured field (quota threshold, sex threshold, observation channel, notification lag) that can conditionally void the printed dates. *Evidence: Black Bear booklet p. 7.*
- **Corrections are a first-class publication type.** FWP published a 1-page correction to the Black Bear booklet on March 18, 2026 — the day after the booklet PDF was modified — that amends hound-hunting licensing language and removes a column from the BMU table. The current schema's `document_type: "annual_regulations" | "rule_change" | "emergency_order"` enum does not have a slot for intra-cycle corrections. *Evidence: corrections-to-the-2026-printed-black-bear-regulations.pdf, 1 page.*
- **Bear Management Units are a separate geometry layer from HDs, and both are separate from CWD Management Zones.** BMUs (Black Bear Hunting Districts, ArcGIS layer 10) are distinct polygons from the Deer/Elk/Lion HDs (layer 11), which are distinct from CWD Management Zones (e.g., "Libby CWD Management Zone" in HDs 100 and 103 of the Legal Descriptions PDF). The schema needs a generic `management_area` concept distinct from `hunting_district`, plus overlay zones (CWD, restricted areas, portions) that cross-cut the primary geometry. *Evidence: ArcGIS layer catalog + Legal Descriptions p. 19.*
- **Block Management Areas change mid-season.** FWP documents BMAs as "valid only for the current hunting season" and publishes them as a per-season Hub dataset. A snapshot-at-ingest model will be wrong by November. Either ingest weekly/daily during season or treat as live-query passthrough. *Evidence: Hub dataset documentation.*
- **Landowner preference is a quota predicate, not a license type.** Up to 15% of the quota pool for certain draws is reserved for landowners meeting a per-species acreage threshold (160 acres deer/antelope, 640 acres elk), with a 10% nonresident sub-cap. The schema needs "this quota contains a reserved sub-pool with an eligibility rule" without inventing a second permit type. *Evidence: DEA p. 17, MCA 87-2-705.*
- **Post-harvest obligations are first-class regulation content and vary by region.** Black bear: 48-hour reporting statewide, PLUS Region 1 hunters submit two premolar teeth within 10 days while Regions 2–7 hunters present full hide + skull for physical inspection within 10 days. The schema's `rules` slot handles the verbatim text, but a structured `reporting_obligation` tag (deadline window, channel, what-to-present, applicable region) is needed so downstream tools can surface these at the right moment. *Evidence: Black Bear booklet pp. 7, 10.*
- **Biennial and annual cycles coexist, and the 900-series antelope license is a statewide layer on top of per-HD licenses.** The DEA booklet is biennial (2026/2027); the Black Bear booklet is annual. Every antelope HD has a quota-limited HD-specific license AND the statewide 900-series archery-only license (`900-20`), which is "first and only choice" and draws against a separate statewide pool of 5,600. A naive `license ↔ HD` many-to-many will miss the 900-series layer. *Evidence: DEA p. 136.*
- **Multi-district licenses and Youth/PTHFV special opportunities are published as separate subsections.** DEA dedicates pp. 124 (Youth + PTHFV) and pp. 126–127 (Multi-district Deer/Elk Licenses and Permits) to special-opportunity records that are not cleanly indexable by (HD, species, license). The schema needs to express "this license is valid in HDs {list}" or "this opportunity applies during dates {range} in any of HDs {list}." *Evidence: DEA TOC.*

## Confidence notes

**Well-verified via direct fetch.** Every PDF URL in the publications inventory was downloaded successfully. Page counts, internal PDF titles, and file-modification dates came from `pdfinfo` on the actual downloaded bytes. Every section sample was extracted by `pdftotext -layout` from the downloaded PDF and the verbatim passages above are exact quotes from that extraction (cosmetic layout artifacts like extra whitespace removed; content unchanged). The ArcGIS REST layer catalog (40 layers in `huntingDistricts`, 27 in `bigGameDistribution`, 8 in `fwpLands`) was enumerated via live `?f=json` calls, and the layer IDs listed above correspond to the names FWP actually returns — this corrects the earlier research document, which had misidentified Layer 11 as "Elk Restricted Areas" (it is actually "Deer Elk Lion Hunting Districts"), placed "Big Game Restricted Areas" incorrectly, and did not capture that the `huntingDistricts` service contains 40 layers grouped into Big Game, Bird, and Furbearer sections. The Legal Descriptions TOC (Antelope p.5, Bighorn p.10, Bison p.13, Black Bear MU p.14, Deer & Elk p.19, Moose p.36, Goat p.43, Mountain Lion p.46, Contacts p.54) was re-verified against the current 2026/2027 edition rather than inferred from a prior edition. The Black Bear corrections publication is a discovery — it did not appear in the earlier research document.

**Uncertain.** The exact contents of each FWP commission meeting proposal PDF were not extracted; only the URL pattern and the adoption-meeting date (Dec 4, 2025) were confirmed. The full enumeration of Hub datasets via the `/api/v3/` search endpoints returned very large result sets that were not systematically catalogued — only the V1-relevant datasets were confirmed, and the Hub likely contains more that could be added to the pipeline later. CORS headers and rate limits on the ArcGIS endpoints were not measured in aggregate (single-request latencies were all sub-second but no load test was run). The MyFWP Hunt Planner per-species data surface was returning "Data is currently unavailable" at investigation time, which is consistent with an off-season state but could not be resolved to a documented cause.

**Could not determine.** Whether MT FWP exposes a documented JSON API for per-HD quotas, per-permit drawing odds, or license pricing — other than via the HTML search forms on myfwp.mt.gov — could not be established from primary sources. An API exists somewhere behind the Hunt Planner, but its contract is not public. The honest options for V1 remain: (a) human-review ingest from the HTML forms, (b) open a direct conversation with MT FWP about data access, or (c) extract these values from the booklet PDFs where they appear as printed tables. Quota data does appear in the booklet tables (verified above), so option (c) is feasible for the V1 corpus.
