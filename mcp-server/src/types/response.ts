/**
 * HuntReady serving-composition response types.
 *
 * These are NOT part of the three-place six-entity schema sync (DDL /
 * Pydantic / TypeScript). Changing these types does NOT trigger a
 * `supabase/migrations/` or `ingestion/lib/schema.py` update.
 *
 * Canonical source of truth: docs/architecture.md § "Response shape:
 * GetRegulationsResponse"
 *
 * `Resolved*` types are query-resolved projections per § "Response shape"
 * (NOT § "Schema types"). Each resolved type adds `confidence` and drops
 * entity-only `id` fields — they represent what the server assembles at
 * query time, not what is stored in the database.
 */

import type {
  SourceCitation,
  VerbatimRule,
  DrawSpec,
  ReservedPool,
  ClosurePredicate,
  WeaponType,
  Residency,
  GeometryRole,
} from "./schema.js";

export interface GetRegulationsResponse {
  query: { lat: number; lng: number; species: string; date: string };

  resolved: {
    jurisdiction: {
      state: string;
      primary_unit: string | null;
      overlays: { role: GeometryRole; name: string }[];
    } | null;
    species_canonical: string | null;
    license_year: number | null;
  };

  seasons: SeasonsSection | null;
  tags: TagsSection | null;
  methods: MethodsSection | null;
  reporting: ReportingSection | null;
  contacts: ContactsSection | null;
  additional_rules: AdditionalRulesSection | null;

  sources: SourceCitation[];

  meta: {
    schema_version: 2;
    generated_at: string;
    data_freshness: {
      most_recent_source_date: string;
      stalest_source_date: string;
      is_stale: boolean;
    } | null;
    coverage: {
      jurisdiction: Coverage;
      species: Coverage;
      overall: Coverage;
    };
    warnings: Warning[];
  };
}

export type Coverage = "full" | "partial" | "none";

export interface SeasonsSection {
  status: "in_season" | "out_of_season" | "no_season_defined" | "conditionally_closed" | "unknown";
  windows: ResolvedSeasonWindow[];
  source: SourceCitation;
}

export interface ResolvedSeasonWindow {
  name: string;
  opens: string;
  closes: string;
  weapon_type: WeaponType | null;
  residency: Residency | null;
  closure_predicate: ClosurePredicate | null;
  verbatim_rule: string;
  page_reference: string | null;
  confidence: "high" | "medium" | "low";
  source: SourceCitation;
}

export interface TagsSection {
  tags: ResolvedTag[];
  source: SourceCitation;
}

export interface ResolvedTag {
  license_code: string;
  name: string;
  kind: "general" | "limited_draw" | "over_the_counter" | "statewide";
  species: string;
  weapon_types: WeaponType[];
  residency: Residency;
  quota: number | null;
  application_deadline: string | null;
  draw_spec: DrawSpec | null;
  reserved_pools: ReservedPool[];
  purchase_url: string;
  verbatim_rule: string;
  confidence: "high" | "medium" | "low";
  source: SourceCitation;
}

export interface MethodsSection {
  allowed: WeaponType[];
  prohibited: WeaponType[];
  verbatim_rule: string;
  confidence: "high" | "medium" | "low";
  source: SourceCitation;
}

export interface ReportingSection {
  obligations: ResolvedReportingObligation[];
  source: SourceCitation;
}

export interface ResolvedReportingObligation {
  kind: "harvest_report" | "mandatory_check" | "tooth_submission" | "hide_skull_presentation" | "cwd_sample" | "other";
  deadline: string;
  deadline_hours: number | null;
  submission_method: "online" | "phone" | "in_person_check_station" | "mail" | "agency_office";
  submission_url: string | null;
  submission_phone: string | null;
  applies_to_regions: string[] | null;
  what_to_present: string[] | null;
  verbatim_rule: string;
  confidence: "high" | "medium" | "low";
  source: SourceCitation;
}

export interface ContactsSection {
  regional_warden: Contact | null;
  regional_office: Contact | null;
  rules_hotline: Contact | null;
}

export interface Contact {
  role: string;
  name: string | null;
  phone: string | null;
  email: string | null;
  url: string | null;
  source: SourceCitation;
}

export interface AdditionalRulesSection {
  rules: VerbatimRule[];
  source: SourceCitation;
}

export interface Warning {
  code:
    | "STALE_SOURCE"
    | "LOW_CONFIDENCE"
    | "CONFLICTING_RULES"
    | "PENDING_CHANGE"
    | "BOUNDARY_AMBIGUOUS"
    | "SUPERSEDED_BY_CORRECTION"
    | "UNSUPPORTED_SCHEMA_VERSION";
  section: "seasons" | "tags" | "methods" | "reporting" | "contacts" | "additional_rules" | "overall";
  message: string;
}
