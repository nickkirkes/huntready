/**
 * HuntReady regulation data model — TypeScript interfaces.
 *
 * This is the TypeScript leg of the three-place schema sync:
 *   1. Postgres DDL — supabase/migrations/
 *   2. Python Pydantic models — ingestion/ingestion/lib/schema.py
 *   3. TypeScript interfaces — this file
 *
 * Canonical source: docs/architecture.md § "Schema types"
 * Kept in manual sync at V1 scale per ADR-005 and ADR-006.
 */

// ---------------------------------------------------------------------------
// Type aliases
// ---------------------------------------------------------------------------

export type WeaponType =
  | "any_legal_weapon"
  | "archery"
  | "rifle"
  | "muzzleloader"
  | "shotgun"
  | "handgun"
  | "crossbow"
  | "traditional_handgun"
  | "heritage_muzzleloader";

export type Residency = "resident" | "nonresident" | "both";

export type GeometryRole =
  | "primary_unit"
  | "portion"
  | "restricted_area"
  | "cwd_management_zone"
  | "bear_management_unit"
  | "block_management_area"
  | "other_overlay"
  | "no_hunt_zone";

// ---------------------------------------------------------------------------
// Supporting types
// ---------------------------------------------------------------------------

export interface SourceCitation {
  id: string;
  agency: string;
  title: string;
  url: string;
  publication_date: string;
  document_type:
    | "annual_regulations"
    | "rule_change"
    | "emergency_order"
    | "correction"
    | "gis_layer";
  supersedes: string | null;
  page_reference: string | null;
}

export interface VerbatimRule {
  text: string;
  page_reference: string | null;
  confidence: "high" | "medium" | "low";
  source: SourceCitation;
}

export interface ClosurePredicate {
  kind: "quota_threshold" | "sex_threshold" | "emergency_order";
  threshold_percent: number | null;
  threshold_sex: "male" | "female" | null;
  notification_channel:
    | "agency_website"
    | "agency_phone"
    | "email_alert"
    | "other";
  observation_channel:
    | "mandatory_reporting"
    | "check_station"
    | "harvest_survey"
    | null;
  verbatim_rule: string;
}

export interface ReservedPool {
  share: number;
  eligibility: {
    kind: "landowner" | "youth" | "hunter_education_recent" | "other";
    min_acres?: number;
    min_acres_contiguous?: boolean;
    min_age?: number;
    max_age?: number;
    notes?: string;
  };
  applies_to_residency: Residency | null;
  nonresident_subcap: number | null;
  verbatim_rule: string;
}

export type PointSystem = {
  kind: "preference_linear" | "bonus_squared" | "bonus_weighted";
  accrual: "annual_on_apply" | "annual_if_purchased";
  reset_on_success: boolean;
  purchase_only_code: string | null;
  inactive_forfeit_years: number | null;
};

export type ResidencyCap = { nonresident_max_share: number };

export type ChoiceConfig = {
  count: number;
  points_used_in_choices: number[];
};

export type AllocationPool = {
  share: number;
  selection:
    | "rank_ordered_by_points"
    | "unweighted_random"
    | "squared_weighted_random"
    | "linear_weighted_random";
  eligibility: {
    min_points?: number;
    residency?: Residency;
    guided?: boolean;
  };
  tie_break?: "random" | "rank_ordered";
};

// ---------------------------------------------------------------------------
// Entity interfaces
// ---------------------------------------------------------------------------

export interface RegulationRecord {
  state: string;
  jurisdiction_code: string;
  species_group: string;
  license_year: number;
  schema_version: number;
  source: SourceCitation;
  ingested_at: string;
  confidence: "high" | "medium" | "low";
  season_definition_ids: string[];
  license_tag_ids: string[];
  reporting_obligation_ids: string[];
  jurisdiction_binding_ids: string[];
  additional_rules: VerbatimRule[];
}

export interface SeasonDefinition {
  id: string;
  name: string;
  opens: string;
  closes: string;
  weapon_type: WeaponType | null;
  residency: Residency | null;
  closure_predicate: ClosurePredicate | null;
  verbatim_rule: string;
  page_reference: string | null;
  source: SourceCitation;
}

export interface LicenseTag {
  id: string;
  license_code: string;
  name: string;
  kind: "general" | "limited_draw" | "over_the_counter" | "statewide";
  species: string;
  weapon_types: WeaponType[];
  residency: Residency;
  quota: number | null;
  quota_range: [number, number] | null;
  purchase_url: string;
  draw_spec_key: {
    state: string;
    hunt_code: string;
    year: number;
  } | null;
  reserved_pools: ReservedPool[];
  verbatim_rule: string;
  source: SourceCitation;
}

export interface DrawSpec {
  state: string;
  hunt_code: string;
  year: number;
  schema_version: number;
  quota: number | null;
  point_system: PointSystem | null;
  residency_cap: ResidencyCap | null;
  choices: ChoiceConfig;
  pools: AllocationPool[];
  draw_phase: "primary" | "secondary" | "leftover";
  successor_hunt_code_key: {
    state: string;
    hunt_code: string;
    year: number;
  } | null;
  application_deadline: string;
  parameters: Record<string, unknown> | null;
  source: SourceCitation;
}

export interface ReportingObligation {
  id: string;
  kind:
    | "harvest_report"
    | "mandatory_check"
    | "tooth_submission"
    | "hide_skull_presentation"
    | "cwd_sample"
    | "other";
  deadline: string;
  deadline_hours: number | null;
  submission_method:
    | "online"
    | "phone"
    | "in_person_check_station"
    | "mail"
    | "agency_office";
  submission_url: string | null;
  submission_phone: string | null;
  applies_to_regions: string[] | null;
  what_to_present: string[] | null;
  verbatim_rule: string;
  source: SourceCitation;
}

export interface Geometry {
  id: string;
  name: string;
  kind:
    | "hunting_district"
    | "gmu"
    | "portion"
    | "bmu"
    | "cwd_zone"
    | "restricted_area"
    | "bma"
    | "state"
    | "other";
  geom: string; // WKT MultiPolygon; PostGIS geography(MultiPolygon, 4326)
  state: string;
  license_year: number | null;
  verbatim_rule: string | null; // verbatim regulatory text from source attributes (e.g., ArcGIS REG/COMMENTS); null when source has none
  legal_description: string | null; // FWP-published prose boundary description; null when source has none
  source: SourceCitation;
}

export interface JurisdictionBinding {
  id: string;
  regulation_record_key: {
    state: string;
    jurisdiction_code: string;
    species_group: string;
    license_year: number;
  };
  geometry_id: string;
  role: GeometryRole;
  verbatim_rule: string | null;
  source: SourceCitation;
}

/**
 * Link: license_tag <-> season_definition (per-license season coverage).
 *
 * Per ADR-018 §1: distinct from the regulation_season link (per-regulation
 * coverage). Both coexist; each answers a different join question.
 */
export interface LicenseSeason {
  license_tag_id: string;
  season_definition_id: string;
}
