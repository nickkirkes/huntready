"""Pydantic v2 models mirroring the HuntReady DDL one-to-one.

These models are the Python leg of the three-place schema sync
(DDL -> Python -> TypeScript). Field names match DDL column names exactly.
Canonical type definitions: docs/architecture.md § "Schema types".

Serialization convention: optional sub-fields default to None. When
serializing to jsonb for DB insert, callers must use
`model.model_dump(exclude_none=True)` so that absent optional fields are
omitted from the JSON rather than written as null. This matches TypeScript's
absent-key semantics for optional properties (`?:`).

See ADR-005, ADR-006, ADR-008, ADR-010, ADR-012.
"""

from __future__ import annotations

import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from shapely import from_wkt, make_valid
from shapely.geometry import MultiPolygon, Polygon

# ---------------------------------------------------------------------------
# Reusable type aliases
# ---------------------------------------------------------------------------

WeaponType = Literal[
    "any_legal_weapon",
    "archery",
    "rifle",
    "muzzleloader",
    "shotgun",
    "handgun",
    "crossbow",
    "traditional_handgun",
    "heritage_muzzleloader",
]

Residency = Literal["resident", "nonresident", "both"]

Confidence = Literal["high", "medium", "low"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _check_non_empty(v: str) -> str:
    """Validate that a string field is non-empty (after stripping whitespace)."""
    if not v.strip():
        msg = "must be a non-empty string"
        raise ValueError(msg)
    return v


# ===========================================================================
# jsonb sub-models (embedded in entity table columns)
# ===========================================================================


class SourceCitation(BaseModel):
    """Source provenance for every regulation record and child entity."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    agency: str
    title: str
    url: str
    publication_date: str
    document_type: Literal[
        "annual_regulations", "rule_change", "emergency_order", "correction",
        "gis_layer",
    ]
    supersedes: str | None = None
    page_reference: str | None = None


class VerbatimRule(BaseModel):
    """Verbatim regulation text with source citation (ADR-008)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    page_reference: str | None = None
    confidence: Confidence
    source: SourceCitation

    @field_validator("text")
    @classmethod
    def _text_non_empty(cls, v: str) -> str:
        return _check_non_empty(v)


class ClosurePredicate(BaseModel):
    """Conditions under which a season may close early."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["quota_threshold", "sex_threshold", "emergency_order"]
    threshold_percent: float | None = None
    threshold_sex: Literal["male", "female"] | None = None
    notification_channel: Literal[
        "agency_website", "agency_phone", "email_alert", "other"
    ]
    observation_channel: Literal[
        "mandatory_reporting", "check_station", "harvest_survey"
    ] | None = None
    verbatim_rule: str

    @field_validator("verbatim_rule")
    @classmethod
    def _verbatim_rule_non_empty(cls, v: str) -> str:
        return _check_non_empty(v)


class ReservedPoolEligibility(BaseModel):
    """Eligibility criteria for a reserved pool (e.g., landowner, youth)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["landowner", "youth", "hunter_education_recent", "other"]
    min_acres: int | None = None
    min_acres_contiguous: bool | None = None
    min_age: int | None = None
    max_age: int | None = None
    notes: str | None = None


class ReservedPool(BaseModel):
    """A reserved allocation pool within a license tag."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    share: float
    eligibility: ReservedPoolEligibility
    applies_to_residency: Residency | None = None
    nonresident_subcap: float | None = None
    verbatim_rule: str

    @field_validator("verbatim_rule")
    @classmethod
    def _verbatim_rule_non_empty(cls, v: str) -> str:
        return _check_non_empty(v)


class PointSystem(BaseModel):
    """Draw point system configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["preference_linear", "bonus_squared", "bonus_weighted"]
    accrual: Literal["annual_on_apply", "annual_if_purchased"]
    reset_on_success: bool
    purchase_only_code: str | None = None
    inactive_forfeit_years: int | None = None


class ResidencyCap(BaseModel):
    """Non-resident allocation cap."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    nonresident_max_share: float


class ChoiceConfig(BaseModel):
    """Draw choice configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    count: int
    points_used_in_choices: list[int]


class AllocationPoolEligibility(BaseModel):
    """Eligibility criteria for a draw allocation pool."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    min_points: int | None = None
    residency: Residency | None = None
    guided: bool | None = None


class AllocationPool(BaseModel):
    """A draw allocation pool with selection method and eligibility."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    share: float
    selection: Literal[
        "rank_ordered_by_points",
        "unweighted_random",
        "squared_weighted_random",
        "linear_weighted_random",
    ]
    eligibility: AllocationPoolEligibility = Field(
        default_factory=AllocationPoolEligibility
    )
    tie_break: Literal["random", "rank_ordered"] | None = None


class DrawSpecKey(BaseModel):
    """Soft FK reference to draw_spec (state, hunt_code, year)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: str
    hunt_code: str
    year: int


# ===========================================================================
# Entity models (matching DDL tables one-to-one)
# ===========================================================================


class RegulationRecord(BaseModel):
    """Anchor entity — one row per (state, jurisdiction_code, species_group, year).

    DDL table: regulation_record
    Composite PK: (state, jurisdiction_code, species_group, license_year)
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: str
    jurisdiction_code: str
    species_group: str
    license_year: int
    schema_version: int = 2
    source: SourceCitation
    ingested_at: datetime.datetime | None = None  # DB provides DEFAULT now()
    confidence: Confidence
    additional_rules: list[VerbatimRule] = Field(default_factory=list)


class SeasonDefinition(BaseModel):
    """Named date range with weapon/residency constraints.

    DDL table: season_definition
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    opens: datetime.date
    closes: datetime.date
    weapon_type: WeaponType | None = None
    residency: Residency | None = None
    closure_predicate: ClosurePredicate | None = None
    verbatim_rule: str
    page_reference: str | None = None
    source: SourceCitation

    @field_validator("verbatim_rule")
    @classmethod
    def _verbatim_rule_non_empty(cls, v: str) -> str:
        return _check_non_empty(v)


class LicenseTag(BaseModel):
    """Permit instrument, optionally referencing a draw_spec via soft FK.

    DDL table: license_tag
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    license_code: str
    name: str
    kind: Literal["general", "limited_draw", "over_the_counter", "statewide"]
    species: str
    weapon_types: list[WeaponType]
    residency: Residency
    quota: int | None = None
    quota_range: tuple[int, int] | None = None  # converted to int4range at insert
    purchase_url: str
    draw_spec_key: DrawSpecKey | None = None
    reserved_pools: list[ReservedPool] = Field(default_factory=list)
    verbatim_rule: str
    source: SourceCitation

    @field_validator("verbatim_rule")
    @classmethod
    def _verbatim_rule_non_empty(cls, v: str) -> str:
        return _check_non_empty(v)


class DrawSpec(BaseModel):
    """Draw mechanics — sibling entity referenced from license_tag by soft FK.

    DDL table: draw_spec
    Composite PK: (state, hunt_code, year)

    ``parameters`` is the ADR-012 escape hatch: only state adapters in
    ``ingestion/states/<state>/`` may write to it. Shared code MUST NOT read it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: str
    hunt_code: str
    year: int
    schema_version: int = 2
    quota: int | None = None
    point_system: PointSystem | None = None
    residency_cap: ResidencyCap | None = None
    choices: ChoiceConfig
    pools: list[AllocationPool]  # required, no default — validated non-empty
    draw_phase: Literal["primary", "secondary", "leftover"]
    successor_hunt_code_key: DrawSpecKey | None = None
    application_deadline: datetime.date
    parameters: dict[str, Any] | None = None
    source: SourceCitation

    @field_validator("pools")
    @classmethod
    def _pools_non_empty(cls, v: list[AllocationPool]) -> list[AllocationPool]:
        if not v:
            msg = "pools must contain at least one AllocationPool"
            raise ValueError(msg)
        return v


class ReportingObligation(BaseModel):
    """Post-harvest or in-season reporting duty.

    DDL table: reporting_obligation
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    kind: Literal[
        "harvest_report",
        "mandatory_check",
        "tooth_submission",
        "hide_skull_presentation",
        "cwd_sample",
        "other",
    ]
    deadline: str
    deadline_hours: int | None = None
    submission_method: Literal[
        "online", "phone", "in_person_check_station", "mail", "agency_office"
    ]
    submission_url: str | None = None
    submission_phone: str | None = None
    applies_to_regions: list[str] | None = None  # None = statewide
    what_to_present: list[str] | None = None
    verbatim_rule: str
    source: SourceCitation

    @field_validator("verbatim_rule")
    @classmethod
    def _verbatim_rule_non_empty(cls, v: str) -> str:
        return _check_non_empty(v)


class Geometry(BaseModel):
    """Geographic polygon for hunting units and overlay zones.

    DDL table: geometry
    The ``geom`` field holds WKT (Well-Known Text). Validated via shapely
    to ensure the geometry is parseable and valid (per CLAUDE.md: every
    geometry goes through ``shapely.make_valid()`` before insert).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    name: str
    kind: Literal[
        "hunting_district",
        "gmu",
        "portion",
        "bmu",
        "cwd_zone",
        "restricted_area",
        "bma",
        "state",
        "other",
    ]
    geom: str  # WKT representation; validated below
    state: str
    license_year: int | None = None
    verbatim_rule: str | None = None
    legal_description: str | None = None
    source: SourceCitation

    @field_validator("geom")
    @classmethod
    def _validate_geom(cls, v: str) -> str:
        parsed = from_wkt(v)
        valid = make_valid(parsed)
        if isinstance(valid, Polygon):
            valid = MultiPolygon([valid])
        if not isinstance(valid, MultiPolygon):
            msg = f"geometry must be a Polygon or MultiPolygon, got {type(valid).__name__}"
            raise ValueError(msg)
        return valid.wkt


class JurisdictionBinding(BaseModel):
    """Overlay relationship between a geometry and a regulation record.

    DDL table: jurisdiction_binding
    Uses flat FK columns matching DDL (not nested object like the TS API shape).
    ``verbatim_rule`` is NULLABLE here — unlike all other entity verbatim_rule fields.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    regulation_record_state: str
    regulation_record_jurisdiction_code: str
    regulation_record_species_group: str
    regulation_record_license_year: int
    geometry_id: str
    role: Literal[
        "primary_unit",
        "portion",
        "restricted_area",
        "cwd_management_zone",
        "bear_management_unit",
        "block_management_area",
        "other_overlay",
    ]
    verbatim_rule: str | None = None
    source: SourceCitation


# ===========================================================================
# Link table models (many-to-many joins)
# ===========================================================================


class RegulationSeason(BaseModel):
    """Link: regulation_record <-> season_definition."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: str
    jurisdiction_code: str
    species_group: str
    license_year: int
    season_definition_id: str


class RegulationLicense(BaseModel):
    """Link: regulation_record <-> license_tag."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: str
    jurisdiction_code: str
    species_group: str
    license_year: int
    license_tag_id: str


class RegulationReporting(BaseModel):
    """Link: regulation_record <-> reporting_obligation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    state: str
    jurisdiction_code: str
    species_group: str
    license_year: int
    reporting_obligation_id: str


class LicenseSeason(BaseModel):
    """Link: license_tag <-> season_definition (per-license season coverage).

    DDL table: license_season
    Per ADR-018 §1: this is *per-license* season coverage, distinct from
    RegulationSeason (which is per-regulation_record season coverage).
    Both link tables coexist; each answers a different join question.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    license_tag_id: str
    season_definition_id: str
