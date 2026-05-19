"""Unit tests for ``ingestion/states/montana/load_draw_specs.py``.

Coverage:
- TestParseApplyBy             — apply_by string → date | None parsing
- TestBuildDeaDrawSpecs        — DEA artifact → (LicenseTag, DrawSpec) pairs
- TestFrontMatterLookupSafetyNet — defensive fallback path + zero-hit baseline
- TestCountGuard               — draw_spec count guard (OQ7)
- TestArtifactCountsRealData   — real-artifact regression locks
- TestMain                     — dry-run smoke + db-connect failure + rollback
- TestDbHelpers                — upsert_draw_spec + update_license_tag_draw_spec_key mocks
- TestNoLibImports             — state-agnostic-clean AST guard

The editable install adds ``ingestion/`` to sys.path so ``states.montana.*``
is directly importable, the same way every sibling adapter test does it.
"""

from __future__ import annotations

import ast
import datetime
import json
import logging
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

import states.montana.load_draw_specs as lds
from ingestion.lib.db import update_license_tag_draw_spec_key, upsert_draw_spec
from ingestion.lib.schema import (
    AllocationPool,
    ChoiceConfig,
    DrawSpec,
    DrawSpecKey,
    SourceCitation,
)
from states.montana.load_draw_specs import (
    _DEFAULT_CHOICES,
    _DEFAULT_POOLS,
    _KNOWN_CROSS_LISTING_OVERRIDES,
    _assert_draw_spec_count_within_guard,
    _build_dea_draw_specs,
    _parse_apply_by,
    _validate_cross_listing_consistency,
    main,
)


# ---------------------------------------------------------------------------
# Shared path constants
# ---------------------------------------------------------------------------

_REAL_ARTIFACT_PATH = (
    Path(__file__).resolve().parent.parent
    / "states" / "montana" / "extracted" / "dea-2026.json"
)

_BASE_PAGE_REF = {
    "bbox": None,
    "extracted_at": "2026-05-08T00:00:00+00:00",
    "page_num_1based": 1,
    "pdf_filename": "synthetic.pdf",
}


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_dea_artifact() -> list[dict]:
    return json.loads(_REAL_ARTIFACT_PATH.read_text())


@pytest.fixture(scope="module")
def real_dea_citation() -> SourceCitation:
    from states.montana.load_seasons_and_licenses import _load_citation_from_sources_yaml  # type: ignore[import-untyped]
    return _load_citation_from_sources_yaml("mt-fwp-dea-2026-booklet")


@pytest.fixture
def mock_dea_citation() -> SourceCitation:
    return SourceCitation(
        id="mt-fwp-dea-2026-booklet",
        agency="Montana FWP",
        title="Deer, Elk, Antelope Regulations 2026",
        url="https://example.com/dea.pdf",
        publication_date="2026-04-27",
        document_type="annual_regulations",
    )


# ---------------------------------------------------------------------------
# Synthetic section / row builders
# ---------------------------------------------------------------------------


def _make_section(
    *,
    species_group: str,
    hd_number: str,
    license_year: int = 2026,
    rows: list[dict],
) -> dict:
    """Build a synthetic DEA artifact section dict matching extract_dea.py output shape."""
    return {
        "hd_name": f"HD {hd_number} synthetic",
        "hd_number": hd_number,
        "species_group": species_group,
        "license_year": license_year,
        "page_reference": _BASE_PAGE_REF,
        "verbatim_text": f"Synthetic verbatim for HD {hd_number}",
        "rows": rows,
    }


def _make_row(
    *,
    license_code: str,
    apply_by: str | None = None,
    quota: int | None = None,
    quota_range: str | None = None,
    opportunity: str | None = None,
    weapon_types: list[str] | None = None,
    extraction_confidence: str = "high",
) -> dict:
    """Build a synthetic DEA artifact row dict matching extract_dea.py output shape."""
    return {
        "license_code": license_code,
        "apply_by": apply_by,
        "quota": quota,
        "quota_range": quota_range,
        "opportunity": opportunity or "Synthetic opportunity",
        "weapon_types": weapon_types or ["any_legal_weapon"],
        "extras": None,
        "season_coverage": {
            "early_season": False,
            "archery_only": False,
            "general": True,
            "heritage_muzzleloader": False,
            "late": False,
        },
        "season_windows": {
            "general": {"window": "Oct 24-Nov 29", "weapon_type_override": None},
        },
        "extraction_confidence": extraction_confidence,
        "page_reference": _BASE_PAGE_REF,
    }


# ---------------------------------------------------------------------------
# TestParseApplyBy
# ---------------------------------------------------------------------------


class TestParseApplyBy:
    def test_parse_jun_1_short(self) -> None:
        assert _parse_apply_by("Jun 1", 2026) == datetime.date(2026, 6, 1)

    def test_parse_june_1_long(self) -> None:
        assert _parse_apply_by("June 1", 2026) == datetime.date(2026, 6, 1)

    def test_parse_april_1(self) -> None:
        assert _parse_apply_by("April 1", 2026) == datetime.date(2026, 4, 1)

    def test_parse_apr_1(self) -> None:
        assert _parse_apply_by("Apr 1", 2026) == datetime.date(2026, 4, 1)

    def test_parse_sept_30(self) -> None:
        # Locks S03.7's "Sept" 4-letter abbreviation pitfall
        assert _parse_apply_by("Sept 30", 2026) == datetime.date(2026, 9, 30)

    def test_parse_sept_dot_30(self) -> None:
        # Trailing period must be tolerated
        assert _parse_apply_by("Sept. 30", 2026) == datetime.date(2026, 9, 30)

    def test_otc_returns_none(self) -> None:
        # OTC signal: the identity should NOT emit a draw_spec
        assert _parse_apply_by("OTC:\nJun 15", 2026) is None

    def test_none_returns_none(self) -> None:
        assert _parse_apply_by(None, 2026) is None

    def test_malformed_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="unrecognized format"):
            _parse_apply_by("someday", 2026)

    def test_invalid_month_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="unrecognized month token"):
            _parse_apply_by("Smarch 1", 2026)

    def test_year_propagates(self) -> None:
        assert _parse_apply_by("Jun 1", 2027) == datetime.date(2027, 6, 1)


# ---------------------------------------------------------------------------
# TestBuildDeaDrawSpecs
# ---------------------------------------------------------------------------


class TestBuildDeaDrawSpecs:
    def test_emits_one_draw_spec_per_limited_draw_identity(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        """3 unique limited_draw identities + 1 OTC + 1 STATEWIDE + 2 General → exactly 3 pairs."""
        sections = [
            # limited_draw identity 1: Deer B License 100-00, apply_by Jun 1
            _make_section(
                species_group="deer", hd_number="100",
                rows=[_make_row(license_code="Deer B License: 100-00", apply_by="Jun 1", quota=10)],
            ),
            # limited_draw identity 2: Elk B License 200-00, apply_by Jun 1
            _make_section(
                species_group="elk", hd_number="200",
                rows=[_make_row(license_code="Elk B License: 200-00", apply_by="Jun 1", quota=20)],
            ),
            # limited_draw identity 3: Antelope License 300-01, apply_by Jun 1
            _make_section(
                species_group="antelope", hd_number="300",
                rows=[_make_row(license_code="Antelope License: 300-01", apply_by="Jun 1", quota=30)],
            ),
            # OTC identity: should be skipped
            _make_section(
                species_group="deer", hd_number="400",
                rows=[_make_row(license_code="Deer B License: 400-00", apply_by="OTC:\nJun 15")],
            ),
            # STATEWIDE antelope: should be skipped (kind='statewide')
            _make_section(
                species_group="antelope", hd_number="STATEWIDE",
                rows=[_make_row(license_code="Antelope License: 900-20", apply_by="June 1", quota=5600)],
            ),
            # General licenses: should be skipped (kind='general')
            _make_section(
                species_group="elk", hd_number="500",
                rows=[
                    _make_row(license_code="General Elk License", apply_by=None),
                    _make_row(license_code="General Elk License", apply_by=None),
                ],
            ),
        ]
        pairs = _build_dea_draw_specs(sections, mock_dea_citation)
        assert len(pairs) == 3

    def test_skips_statewide_900_20(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        """STATEWIDE 900-20 antelope row → 0 draw_spec pairs."""
        sections = [
            _make_section(
                species_group="antelope", hd_number="STATEWIDE",
                rows=[_make_row(license_code="Antelope License: 900-20", apply_by="June 1", quota=5600)],
            ),
        ]
        pairs = _build_dea_draw_specs(sections, mock_dea_citation)
        assert pairs == []

    def test_skips_otc_b_licenses(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        """B License with OTC apply_by → kind='over_the_counter' → 0 pairs."""
        sections = [
            _make_section(
                species_group="deer", hd_number="124",
                rows=[_make_row(license_code="Deer B License: 124-00", apply_by="OTC:\nJun 15")],
            ),
        ]
        pairs = _build_dea_draw_specs(sections, mock_dea_citation)
        assert pairs == []

    def test_dedupe_collapses_duplicate_rows(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        """3 rows of same (species, hd, license_code) → 1 draw_spec pair."""
        rows = [
            _make_row(license_code="Deer B License: 262-00", apply_by="Jun 1", quota=10),
            _make_row(license_code="Deer B License: 262-00", apply_by="Jun 1", quota=10),
            _make_row(license_code="Deer B License: 262-00", apply_by="Jun 1", quota=10),
        ]
        sections = [_make_section(species_group="deer", hd_number="262", rows=rows)]
        pairs = _build_dea_draw_specs(sections, mock_dea_citation)
        assert len(pairs) == 1

    def test_application_deadline_first_non_null_wins(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        """Row A apply_by='Jun 1', row B apply_by=None → deadline=date(2026, 6, 1)."""
        rows = [
            _make_row(license_code="Elk B License: 170-00", apply_by="Jun 1", quota=50),
            _make_row(license_code="Elk B License: 170-00", apply_by=None, quota=50),
        ]
        sections = [_make_section(species_group="elk", hd_number="170", rows=rows)]
        pairs = _build_dea_draw_specs(sections, mock_dea_citation)
        assert len(pairs) == 1
        _, spec = pairs[0]
        assert spec.application_deadline == datetime.date(2026, 6, 1)

    def test_application_deadline_otc_demotes_to_no_draw_spec(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        """Row A apply_by='OTC:\\nJun 15', row B apply_by='Jun 1' → OTC-wins → 0 pairs."""
        rows = [
            _make_row(license_code="Deer B License: 213-02", apply_by="OTC:\nJun 15"),
            _make_row(license_code="Deer B License: 213-02", apply_by="Jun 1"),
        ]
        sections = [_make_section(species_group="deer", hd_number="213", rows=rows)]
        pairs = _build_dea_draw_specs(sections, mock_dea_citation)
        # OTC-wins reclassifies the entire identity as over_the_counter → skipped
        assert pairs == []

    def test_year_drift_within_identity_fails_loud(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        """Two rows of the same identity with different license_year → RuntimeError."""
        sections = [
            _make_section(
                species_group="elk", hd_number="100", license_year=2026,
                rows=[_make_row(license_code="Elk B License: 100-00", apply_by="Jun 1")],
            ),
            _make_section(
                species_group="elk", hd_number="100", license_year=2027,
                rows=[_make_row(license_code="Elk B License: 100-00", apply_by="Jun 1")],
            ),
        ]
        with pytest.raises(RuntimeError, match="license_year drift"):
            _build_dea_draw_specs(sections, mock_dea_citation)

    def test_hunt_code_is_full_license_code(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        """draw_spec.hunt_code == full license_code, not just the numeric suffix."""
        rows = [_make_row(license_code="Deer B License: 262-50", apply_by="Jun 1", quota=10)]
        sections = [_make_section(species_group="deer", hd_number="262", rows=rows)]
        pairs = _build_dea_draw_specs(sections, mock_dea_citation)
        assert len(pairs) == 1
        _, spec = pairs[0]
        assert spec.hunt_code == "Deer B License: 262-50"

    def test_quota_propagates_from_license_tag(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        """draw_spec.quota == license_tag.quota (propagated, not separately derived)."""
        rows = [_make_row(license_code="Elk B License: 300-00", apply_by="Jun 1", quota=75)]
        sections = [_make_section(species_group="elk", hd_number="300", rows=rows)]
        pairs = _build_dea_draw_specs(sections, mock_dea_citation)
        assert len(pairs) == 1
        tag, spec = pairs[0]
        assert spec.quota == tag.quota
        assert spec.quota == 75

    def test_hardcoded_defaults_applied(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        """V1 hardcoded defaults: choices, pools, draw_phase, parameters, etc."""
        rows = [_make_row(license_code="Deer B License: 124-00", apply_by="Jun 1", quota=25)]
        sections = [_make_section(species_group="deer", hd_number="124", rows=rows)]
        pairs = _build_dea_draw_specs(sections, mock_dea_citation)
        assert len(pairs) == 1
        _, spec = pairs[0]
        assert spec.choices == _DEFAULT_CHOICES
        assert spec.pools == _DEFAULT_POOLS
        assert spec.draw_phase == "primary"
        assert spec.parameters is None
        assert spec.point_system is None
        assert spec.residency_cap is None


# ---------------------------------------------------------------------------
# TestFrontMatterLookupSafetyNet
# ---------------------------------------------------------------------------


class TestFrontMatterLookupSafetyNet:
    def test_lookup_fires_when_all_apply_bys_null(
        self, mock_dea_citation: SourceCitation, caplog: pytest.LogCaptureFixture
    ) -> None:
        """B License with all apply_by=None → fallback lookup fires; deadline resolved; WARN emitted."""
        rows = [_make_row(license_code="Deer B License: 999-99", apply_by=None, quota=5)]
        sections = [_make_section(species_group="deer", hd_number="999", rows=rows)]

        with caplog.at_level(logging.WARNING):
            pairs = _build_dea_draw_specs(sections, mock_dea_citation)

        assert len(pairs) == 1
        _, spec = pairs[0]
        # "b_license" fallback for deer → June 1
        assert spec.application_deadline == datetime.date(2026, 6, 1)
        assert lds._lookup_fallback_hits == 1

        warn_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("Front-matter deadline-lookup fallback fired" in m for m in warn_messages), (
            f"Expected front-matter fallback WARN in log; got: {warn_messages}"
        )

    def test_lookup_miss_raises_runtimeerror(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        """An identity with no parseable apply_by AND no lookup key raises RuntimeError.

        Antelope Permit has no entry in _DEA_DEADLINE_LOOKUP so if it appears with
        only None apply_by cells, the lookup miss should fail loud.
        """
        # Construct a code that starts with "Permit:" to hit the "permit" branch,
        # but for species "antelope" — not present in _DEA_DEADLINE_LOOKUP
        rows = [_make_row(license_code="Antelope Permit: 888-00", apply_by=None, quota=5)]
        sections = [_make_section(species_group="antelope", hd_number="888", rows=rows)]
        with pytest.raises(RuntimeError, match="front-matter lookup miss"):
            _build_dea_draw_specs(sections, mock_dea_citation)

    def test_lookup_zero_hits_against_real_artifact(
        self, real_dea_artifact: list[dict], real_dea_citation: SourceCitation
    ) -> None:
        """Regression lock: V1 baseline must produce exactly 0 fallback hits."""
        _build_dea_draw_specs(real_dea_artifact, real_dea_citation)
        assert lds._lookup_fallback_hits == 0, (
            f"Expected 0 front-matter fallback hits against real artifact; "
            f"got {lds._lookup_fallback_hits}. Drift signal — investigate."
        )


# ---------------------------------------------------------------------------
# TestCountGuard
# ---------------------------------------------------------------------------


class TestCountGuard:
    # Expected=388; lower=int(388*0.7)=271; upper=int(388*1.3)=504

    def test_count_at_baseline_passes(self) -> None:
        _assert_draw_spec_count_within_guard(388)

    def test_count_at_lower_bound_passes(self) -> None:
        _assert_draw_spec_count_within_guard(271)

    def test_count_at_upper_bound_passes(self) -> None:
        _assert_draw_spec_count_within_guard(504)

    def test_count_below_band_raises(self) -> None:
        with pytest.raises(RuntimeError, match="draw_spec count guard"):
            _assert_draw_spec_count_within_guard(200)

    def test_count_above_band_raises(self) -> None:
        with pytest.raises(RuntimeError, match="draw_spec count guard"):
            _assert_draw_spec_count_within_guard(600)

    def test_count_zero_raises(self) -> None:
        with pytest.raises(RuntimeError, match="draw_spec count guard"):
            _assert_draw_spec_count_within_guard(0)


# ---------------------------------------------------------------------------
# TestArtifactCountsRealData
# ---------------------------------------------------------------------------


class TestArtifactCountsRealData:
    def test_real_artifact_yields_388_draw_specs(
        self, real_dea_artifact: list[dict], real_dea_citation: SourceCitation
    ) -> None:
        pairs = _build_dea_draw_specs(real_dea_artifact, real_dea_citation)
        assert len(pairs) == 388, (
            f"Expected 388 draw_spec pairs; got {len(pairs)}. "
            "Drift signal — investigate T1's OTC-wins heuristic or dedup."
        )

    def test_real_artifact_otc_kind_count_is_162(
        self, real_dea_artifact: list[dict], real_dea_citation: SourceCitation
    ) -> None:
        from states.montana.load_seasons_and_licenses import _build_dea_license_tags  # type: ignore[import-untyped]
        tags = _build_dea_license_tags(real_dea_artifact, real_dea_citation)
        deduped = {t.id: t.kind for t in tags}
        otc_count = sum(1 for k in deduped.values() if k == "over_the_counter")
        assert otc_count == 162, (
            f"Expected 162 over_the_counter identities; got {otc_count}. "
            "Drift signal — investigate T1's OTC-wins heuristic."
        )

    def test_real_artifact_limited_draw_kind_count_is_388(
        self, real_dea_artifact: list[dict], real_dea_citation: SourceCitation
    ) -> None:
        from states.montana.load_seasons_and_licenses import _build_dea_license_tags  # type: ignore[import-untyped]
        tags = _build_dea_license_tags(real_dea_artifact, real_dea_citation)
        deduped = {t.id: t.kind for t in tags}
        ld_count = sum(1 for k in deduped.values() if k == "limited_draw")
        assert ld_count == 388, (
            f"Expected 388 limited_draw identities; got {ld_count}. "
            "Drift signal — investigate T1's OTC-wins heuristic."
        )

    def test_real_artifact_no_statewide_in_draw_specs(
        self, real_dea_artifact: list[dict], real_dea_citation: SourceCitation
    ) -> None:
        pairs = _build_dea_draw_specs(real_dea_artifact, real_dea_citation)
        statewide_codes = [spec.hunt_code for _, spec in pairs if "900-20" in spec.hunt_code]
        assert statewide_codes == [], (
            f"draw_spec list must not contain STATEWIDE 900-20; found: {statewide_codes}"
        )

    def test_real_artifact_all_draw_specs_have_unique_license_tag_id(
        self, real_dea_artifact: list[dict], real_dea_citation: SourceCitation
    ) -> None:
        """Each (state, hunt_code, year) triple forms the draw_spec PK, but the
        same license_code can appear in multiple HDs (e.g., 'Deer B License: 004-01'
        across several portions sections). The dedup in _build_dea_draw_specs is
        keyed on LicenseTag.id (which embeds species + hd + license_code), so each
        emitted pair has a unique tag.id. That uniqueness is the regression lock here.
        """
        pairs = _build_dea_draw_specs(real_dea_artifact, real_dea_citation)
        tag_ids = [tag.id for tag, _ in pairs]
        assert len(tag_ids) == len(set(tag_ids)), (
            "Duplicate LicenseTag.id values in draw_spec pairs — dedup regression; "
            f"duplicates: {[tid for tid in tag_ids if tag_ids.count(tid) > 1][:10]}"
        )


# ---------------------------------------------------------------------------
# TestCrossListingConsistency
# ---------------------------------------------------------------------------


def _make_pair(
    *,
    hunt_code: str,
    year: int = 2026,
    quota: int | None = 50,
    application_deadline: datetime.date | None = datetime.date(2026, 6, 1),
    mock_citation: SourceCitation | None = None,
) -> tuple[object, DrawSpec]:
    """Build a (LicenseTag stub, DrawSpec) pair for consistency validator tests.

    LicenseTag is constructed minimally via _make_row/_make_section → _build_dea_draw_specs,
    or directly as a stub object since the validator only reads DrawSpec fields.
    We use a lightweight approach: build the DrawSpec directly and use a Mock for the tag.
    """
    from unittest.mock import Mock as _Mock
    from ingestion.lib.schema import SourceCitation as _SC

    citation = mock_citation or _SC(
        id="mt-fwp-dea-2026-booklet",
        agency="Montana FWP",
        title="DEA 2026",
        url="https://example.com/dea.pdf",
        publication_date="2026-04-27",
        document_type="annual_regulations",
    )
    tag = _Mock()
    tag.id = f"mt-elk-hd-synthetic-{hunt_code}"
    spec = DrawSpec(
        state="US-MT",
        hunt_code=hunt_code,
        year=year,
        quota=quota,
        point_system=None,
        residency_cap=None,
        choices=ChoiceConfig(count=1, points_used_in_choices=[1]),
        pools=[AllocationPool(share=1.0, selection="unweighted_random")],
        draw_phase="primary",
        successor_hunt_code_key=None,
        application_deadline=application_deadline,
        parameters=None,
        source=citation,
    )
    return tag, spec


class TestCrossListingConsistency:
    """Locks the (hunt_code, year) consistency validator + override behavior.

    Cross-listed license_codes can appear in multiple HD sections. When their
    structural fields disagree, _validate_cross_listing_consistency must either
    apply a documented override (WARN log) or fail loud.
    """

    def test_single_constituent_pk_passes_through(self) -> None:
        """One pair → returned unchanged (length=1)."""
        tag, spec = _make_pair(hunt_code="Elk B License: 100-00")
        result = _validate_cross_listing_consistency([(tag, spec)])
        assert len(result) == 1
        returned_tag, returned_spec = result[0]
        assert returned_spec.hunt_code == "Elk B License: 100-00"
        assert returned_spec.quota == 50

    def test_multi_constituent_agreeing_passes_through(self) -> None:
        """3 pairs same (hunt_code, year), agreeing quota+deadline → 3 pairs returned."""
        pairs = [
            _make_pair(hunt_code="Elk B License: 200-00", quota=75),
            _make_pair(hunt_code="Elk B License: 200-00", quota=75),
            _make_pair(hunt_code="Elk B License: 200-00", quota=75),
        ]
        result = _validate_cross_listing_consistency(pairs)
        assert len(result) == 3
        for _, spec in result:
            assert spec.quota == 75

    def test_quota_conflict_without_override_raises(self) -> None:
        """2 pairs same PK, different quotas, PK NOT in _KNOWN_CROSS_LISTING_OVERRIDES
        → RuntimeError with diagnostic naming the PK."""
        hunt_code = "Elk B License: 999-97"  # Not in overrides
        assert (hunt_code, 2026) not in _KNOWN_CROSS_LISTING_OVERRIDES, (
            f"Test precondition failed: {(hunt_code, 2026)!r} must not be in overrides"
        )
        pairs = [
            _make_pair(hunt_code=hunt_code, quota=100),
            _make_pair(hunt_code=hunt_code, quota=200),
        ]
        with pytest.raises(RuntimeError, match="_validate_cross_listing_consistency"):
            _validate_cross_listing_consistency(pairs)

    def test_quota_conflict_error_names_the_pk(self) -> None:
        """RuntimeError message must name the conflicting PK for triage."""
        hunt_code = "Elk B License: 999-98"
        assert (hunt_code, 2026) not in _KNOWN_CROSS_LISTING_OVERRIDES
        pairs = [
            _make_pair(hunt_code=hunt_code, quota=100),
            _make_pair(hunt_code=hunt_code, quota=200),
        ]
        with pytest.raises(RuntimeError) as exc_info:
            _validate_cross_listing_consistency(pairs)
        assert hunt_code in str(exc_info.value), (
            f"RuntimeError must mention the hunt_code {hunt_code!r}; "
            f"got: {exc_info.value!r}"
        )

    def test_quota_conflict_with_override_rewrites_to_canonical(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """2 pairs for ("Elk B License: 210-03", 2026) with quotas 300 and 200
        → resolved pairs all have quota=300 (canonical); WARN log emitted."""
        hunt_code = "Elk B License: 210-03"
        assert (hunt_code, 2026) in _KNOWN_CROSS_LISTING_OVERRIDES, (
            "Test precondition: override must exist for this PK"
        )
        pairs = [
            _make_pair(hunt_code=hunt_code, quota=300),  # home HD
            _make_pair(hunt_code=hunt_code, quota=200),  # cross-listed HD
        ]
        with caplog.at_level(logging.WARNING):
            result = _validate_cross_listing_consistency(pairs)

        assert len(result) == 2
        for _, spec in result:
            assert spec.quota == 300, (
                f"Override must rewrite all constituents to canonical quota=300; "
                f"got quota={spec.quota}"
            )

        warn_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("Cross-listing override applied" in m for m in warn_messages), (
            f"Expected WARN log for cross-listing override; got: {warn_messages}"
        )

    def test_deadline_conflict_without_override_raises(self) -> None:
        """2 pairs same PK, different application_deadlines, no override → RuntimeError."""
        hunt_code = "Elk B License: 999-96"
        assert (hunt_code, 2026) not in _KNOWN_CROSS_LISTING_OVERRIDES
        pairs = [
            _make_pair(hunt_code=hunt_code, application_deadline=datetime.date(2026, 6, 1)),
            _make_pair(hunt_code=hunt_code, application_deadline=datetime.date(2026, 4, 1)),
        ]
        with pytest.raises(RuntimeError, match="_validate_cross_listing_consistency"):
            _validate_cross_listing_consistency(pairs)

    def test_override_only_rewrites_specified_fields(self) -> None:
        """Override specifying quota-only: matching deadlines pass through; quota conflict resolved."""
        hunt_code = "Elk B License: 210-03"
        assert (hunt_code, 2026) in _KNOWN_CROSS_LISTING_OVERRIDES
        override = _KNOWN_CROSS_LISTING_OVERRIDES[(hunt_code, 2026)]
        assert "quota" in override
        assert "application_deadline" not in override, (
            "Test precondition: override must specify quota only, not deadline"
        )

        # Same deadline for both constituents — deadline must not be touched
        common_deadline = datetime.date(2026, 6, 1)
        pairs = [
            _make_pair(hunt_code=hunt_code, quota=300, application_deadline=common_deadline),
            _make_pair(hunt_code=hunt_code, quota=200, application_deadline=common_deadline),
        ]
        result = _validate_cross_listing_consistency(pairs)
        assert len(result) == 2
        for _, spec in result:
            assert spec.quota == 300
            assert spec.application_deadline == common_deadline, (
                "Deadline must be preserved unchanged when override doesn't specify it"
            )

    def test_deadline_conflict_with_quota_only_override_raises(self) -> None:
        """Override specifying quota-only but constituents ALSO disagree on deadline
        → RuntimeError naming `application_deadline` and the override gap.

        Locks the P3 cubic-review fix: a partial override (covers quota but not
        deadline) that leaves a deadline conflict unresolved must fail loud rather
        than silently produce last-write-wins via UPSERT.

        Synthetic scenario: PK=("Elk B License: 210-03", 2026) has an existing
        quota-only override. We feed it constituents with BOTH quota AND deadline
        conflicts. The validator must detect that the override doesn't cover the
        deadline conflict and raise RuntimeError naming 'application_deadline'.
        """
        hunt_code = "Elk B License: 210-03"
        assert (hunt_code, 2026) in _KNOWN_CROSS_LISTING_OVERRIDES, (
            "Test precondition: quota-only override must exist for this PK"
        )
        override = _KNOWN_CROSS_LISTING_OVERRIDES[(hunt_code, 2026)]
        assert "quota" in override, "Test precondition: override specifies quota"
        assert "application_deadline" not in override, (
            "Test precondition: override must NOT specify application_deadline"
        )

        # Both quota AND deadline conflict — but override only covers quota
        pairs = [
            _make_pair(
                hunt_code=hunt_code,
                quota=300,
                application_deadline=datetime.date(2026, 6, 1),
            ),
            _make_pair(
                hunt_code=hunt_code,
                quota=200,
                application_deadline=datetime.date(2026, 4, 1),  # different!
            ),
        ]
        with pytest.raises(RuntimeError) as exc_info:
            _validate_cross_listing_consistency(pairs)

        error_msg = str(exc_info.value)
        assert "application_deadline" in error_msg, (
            f"RuntimeError must name 'application_deadline' as the uncovered "
            f"conflicting field; got: {error_msg!r}"
        )
        # Must also mention the override gap (not just a generic no-override error)
        assert "override" in error_msg.lower(), (
            f"RuntimeError must indicate the issue is with the override coverage; "
            f"got: {error_msg!r}"
        )

    def test_real_artifact_hd_210_override_applied(
        self,
        real_dea_artifact: list[dict],
        real_dea_citation: SourceCitation,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Load real artifact, build pairs, call validator.
        - WARN log fires for ("Elk B License: 210-03", 2026)
        - All returned pairs for that PK have quota=300
        """
        pairs = _build_dea_draw_specs(real_dea_artifact, real_dea_citation)

        with caplog.at_level(logging.WARNING):
            resolved = _validate_cross_listing_consistency(pairs)

        warn_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any(
            "Cross-listing override applied" in m and "210-03" in m
            for m in warn_messages
        ), (
            f"Expected WARN log mentioning '210-03'; got: {warn_messages}"
        )

        hd_210_pairs = [
            (tag, spec) for tag, spec in resolved
            if spec.hunt_code == "Elk B License: 210-03"
        ]
        assert len(hd_210_pairs) == 4, (
            f"Expected 4 pairs for 'Elk B License: 210-03' (home HD 210 + "
            f"cross-listed HDs 211, 212, 216); got {len(hd_210_pairs)}"
        )
        for _, spec in hd_210_pairs:
            assert spec.quota == 300, (
                f"All 4 pairs must have canonical quota=300; got quota={spec.quota}"
            )

    def test_real_artifact_validator_only_fires_for_hd_210(
        self,
        real_dea_artifact: list[dict],
        real_dea_citation: SourceCitation,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """After validator: exactly ONE WARN log entry (HD 210 only).
        All other cross-listed PKs (31 of them) pass through unchanged.
        """
        pairs = _build_dea_draw_specs(real_dea_artifact, real_dea_citation)

        with caplog.at_level(logging.WARNING):
            _validate_cross_listing_consistency(pairs)

        override_warns = [
            r.getMessage() for r in caplog.records
            if r.levelno == logging.WARNING and "Cross-listing override applied" in r.getMessage()
        ]
        assert len(override_warns) == 1, (
            f"Expected exactly 1 cross-listing override WARN (HD 210 only); "
            f"got {len(override_warns)}: {override_warns}"
        )

    def test_override_rewrites_both_tag_and_spec_quota(
        self,
        real_dea_artifact: list[dict],
        real_dea_citation: SourceCitation,
    ) -> None:
        """When override applies, BOTH license_tag.quota AND draw_spec.quota are
        rewritten to the canonical value. Locks against the cubic-P2 finding that
        draw_spec.quota was rewritten but license_tag.quota was left at the original
        per-HD cap value, producing inconsistency between the two tables.
        """
        hunt_code = "Elk B License: 210-03"
        assert (hunt_code, 2026) in _KNOWN_CROSS_LISTING_OVERRIDES, (
            "Test precondition: override must exist for this PK"
        )
        override = _KNOWN_CROSS_LISTING_OVERRIDES[(hunt_code, 2026)]
        canonical_quota = override["quota"]
        assert canonical_quota == 300

        pairs = _build_dea_draw_specs(real_dea_artifact, real_dea_citation)
        resolved = _validate_cross_listing_consistency(pairs)

        hd_210_pairs = [
            (tag, spec) for tag, spec in resolved
            if spec.hunt_code == hunt_code
        ]
        assert len(hd_210_pairs) == 4, (
            f"Expected 4 pairs for {hunt_code!r}; got {len(hd_210_pairs)}"
        )
        for tag, spec in hd_210_pairs:
            assert spec.quota == 300, (
                f"draw_spec.quota must be canonical 300; got {spec.quota} for tag.id={tag.id}"
            )
            assert tag.quota == 300, (
                f"license_tag.quota must be canonical 300; got {tag.quota} for tag.id={tag.id}. "
                f"Cubic-P2: override must rewrite BOTH tag.quota AND spec.quota."
            )

    def test_real_artifact_hd_210_license_tag_quota_rewritten(
        self,
        real_dea_artifact: list[dict],
        real_dea_citation: SourceCitation,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Real-artifact regression: after validator, all 4 HD 210 cross-listed
        license_tags have quota=300 (not 200), matching the override applied to
        the draw_spec. The WARN log fires confirming the override path was taken.
        """
        pairs = _build_dea_draw_specs(real_dea_artifact, real_dea_citation)

        with caplog.at_level(logging.WARNING):
            resolved = _validate_cross_listing_consistency(pairs)

        # Confirm WARN fired
        warn_messages = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("Cross-listing override applied" in m and "210-03" in m for m in warn_messages), (
            f"Expected WARN for '210-03'; got: {warn_messages}"
        )

        hd_210_pairs = [
            (tag, spec) for tag, spec in resolved
            if spec.hunt_code == "Elk B License: 210-03"
        ]
        assert len(hd_210_pairs) == 4, (
            f"Expected 4 pairs for 'Elk B License: 210-03'; got {len(hd_210_pairs)}"
        )
        for tag, spec in hd_210_pairs:
            assert tag.quota == 300, (
                f"license_tag.quota must be 300 (not 200) after validator; "
                f"got {tag.quota} for tag.id={tag.id}"
            )
            assert spec.quota == 300, (
                f"draw_spec.quota must be 300 after validator; "
                f"got {spec.quota} for tag.id={tag.id}"
            )


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------


def _make_mock_conn() -> tuple[Mock, Mock]:
    """Construct a psycopg3-style mock connection + cursor with CM wiring."""
    mock_cursor = Mock()
    mock_cursor.rowcount = 1  # UPDATE matches one row (success path)

    mock_cursor_cm = Mock()
    mock_cursor_cm.__enter__ = Mock(return_value=mock_cursor)
    mock_cursor_cm.__exit__ = Mock(return_value=None)

    mock_conn = Mock()
    mock_conn.cursor = Mock(return_value=mock_cursor_cm)
    return mock_conn, mock_cursor


class TestMain:
    def test_dry_run_smoke(self, caplog: pytest.LogCaptureFixture) -> None:
        """Dry-run must build all records, pass count guard, return 0."""
        with caplog.at_level(logging.INFO):
            exit_code = main(["--dry-run"])
        assert exit_code == 0
        # The dry-run log must mention the draw_spec count
        assert "388" in caplog.text, (
            f"Expected '388' in dry-run log output; got: {caplog.text!r}"
        )

    def test_dry_run_does_not_call_db_connect(self) -> None:
        """Dry-run must NOT touch the database."""
        with patch.object(lds, "connect") as mock_connect:
            exit_code = main(["--dry-run"])
        assert exit_code == 0
        mock_connect.assert_not_called()

    def test_dry_run_fails_on_fallback_hits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fallback-hit check fires for dry-run, not only for real runs.

        Locks the P2 cubic-review fix: the _lookup_fallback_hits guard must
        fire BEFORE the dry-run short-circuit so CI smoke cannot silently
        pass while a real ingest would abort on missing per-row deadlines.

        Strategy: monkeypatch _build_dea_draw_specs to set _lookup_fallback_hits
        to a non-zero value after the real builder runs (simulating a new license
        type that bypasses per-row apply_by), then call main(["--dry-run"]) and
        assert RuntimeError is raised before return 0.
        """
        original_build = lds._build_dea_draw_specs

        def build_with_fallback_hit(
            dea_artifact: list[dict], dea_citation: object
        ) -> list[tuple]:
            result = original_build(dea_artifact, dea_citation)
            # Simulate one fallback hit that the builder would have counted
            lds._lookup_fallback_hits = 1
            return result

        monkeypatch.setattr(lds, "_build_dea_draw_specs", build_with_fallback_hit)

        with pytest.raises(RuntimeError, match="fallback"):
            main(["--dry-run"])

    def test_db_connect_failure_aborts_before_writes(self) -> None:
        """connect() raising → exception propagates; no upsert calls."""
        with (
            patch.object(lds, "connect", side_effect=RuntimeError("no DB")),
            patch.object(lds, "upsert_license_tag") as mock_upsert_lt,
            patch.object(lds, "upsert_draw_spec") as mock_upsert_ds,
            patch.object(lds, "update_license_tag_draw_spec_key") as mock_update,
        ):
            with pytest.raises(RuntimeError, match="no DB"):
                main([])
        mock_upsert_lt.assert_not_called()
        mock_upsert_ds.assert_not_called()
        mock_update.assert_not_called()

    def test_rollback_on_phase_2_failure(self) -> None:
        """upsert_draw_spec raising on 5th call → rollback called, commit NOT called."""
        mock_conn, _ = _make_mock_conn()

        call_count = {"n": 0}

        def failing_upsert_draw_spec(conn: object, spec: object) -> None:
            call_count["n"] += 1
            if call_count["n"] >= 5:
                raise RuntimeError("simulated phase-2 failure on call 5")

        with (
            patch.object(lds, "connect", return_value=mock_conn),
            patch.object(lds, "upsert_license_tag"),
            patch.object(lds, "upsert_draw_spec", side_effect=failing_upsert_draw_spec),
            patch.object(lds, "update_license_tag_draw_spec_key"),
        ):
            with pytest.raises(RuntimeError, match="simulated phase-2 failure"):
                main([])

        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()

    def test_phase1_license_tags_reflect_override_quotas_for_hd_210(self) -> None:
        """Cubic-P2 end-to-end lock: Phase 1 upsert_license_tag calls for the 3
        cross-listed HD 210 tags (HDs 211/212/216) must carry quota=300 (the
        canonical override value), NOT quota=200 (the original per-HD cap).

        Without the Step-4b propagation in main(), Phase 1 would write the
        original per-HD cap (200) while Phase 2 writes 300, leaving
        license_tag.quota and draw_spec.quota inconsistent for the same license.

        Strategy: monkeypatch upsert_license_tag to capture all calls, run main()
        against a no-op mock connection, then assert captured license_tag objects
        for the HD 211/212/216 identities have quota=300.
        """
        from ingestion.lib.schema import LicenseTag as _LicenseTag

        captured_license_tags: list[_LicenseTag] = []

        def capturing_upsert_license_tag(conn: object, tag: _LicenseTag) -> None:
            captured_license_tags.append(tag)

        mock_conn, _ = _make_mock_conn()
        with (
            patch.object(lds, "connect", return_value=mock_conn),
            patch.object(lds, "upsert_license_tag", side_effect=capturing_upsert_license_tag),
            patch.object(lds, "upsert_draw_spec"),
            patch.object(lds, "update_license_tag_draw_spec_key"),
        ):
            exit_code = main([])

        assert exit_code == 0, f"main() returned non-zero: {exit_code}"

        # Find cross-listed tags (HDs 211, 212, 216 — NOT the home HD 210).
        # dea_license_tags may contain duplicates per-ID (one per artifact row),
        # so we assert that ALL captured instances with these IDs carry quota=300.
        cross_listed_ids = {
            "MT-HD-211-elk-elk-b-210-03-2026",
            "MT-HD-212-elk-elk-b-210-03-2026",
            "MT-HD-216-elk-elk-b-210-03-2026",
        }
        cross_listed_tags = [
            tag for tag in captured_license_tags if tag.id in cross_listed_ids
        ]
        assert len(cross_listed_tags) >= 3, (
            f"Expected at least one upsert_license_tag call per cross-listed HD 210 tag; "
            f"got {len(cross_listed_tags)}. "
            f"IDs seen with '210': {[t.id for t in captured_license_tags if '210-03' in t.id]}"
        )
        for tag in cross_listed_tags:
            assert tag.quota == 300, (
                f"Phase 1 must write quota=300 (override) for {tag.id}; "
                f"got quota={tag.quota}. Cubic-P2: propagation step missing."
            )


# ---------------------------------------------------------------------------
# TestDbHelpers
# ---------------------------------------------------------------------------


def _make_test_draw_spec(
    *,
    quota: int | None = 50,
    point_system: object = None,
    residency_cap: object = None,
    successor_hunt_code_key: object = None,
    parameters: dict | None = None,
) -> DrawSpec:
    """Construct a minimal DrawSpec for db helper tests."""
    from ingestion.lib.schema import SourceCitation
    citation = SourceCitation(
        id="mt-fwp-dea-2026-booklet",
        agency="Montana FWP",
        title="DEA 2026",
        url="https://example.com/dea.pdf",
        publication_date="2026-04-27",
        document_type="annual_regulations",
    )
    return DrawSpec(
        state="US-MT",
        hunt_code="Deer B License: 262-50",
        year=2026,
        quota=quota,
        point_system=point_system,  # type: ignore[arg-type]
        residency_cap=residency_cap,  # type: ignore[arg-type]
        choices=ChoiceConfig(count=1, points_used_in_choices=[1]),
        pools=[AllocationPool(share=1.0, selection="unweighted_random")],
        draw_phase="primary",
        successor_hunt_code_key=successor_hunt_code_key,  # type: ignore[arg-type]
        application_deadline=datetime.date(2026, 6, 1),
        parameters=parameters,
        source=citation,
    )


class TestUpsertDrawSpec:
    def _make_cursor_cm(self) -> tuple[Mock, Mock]:
        """Mock cursor context manager."""
        cursor = Mock()
        cm = Mock()
        cm.__enter__ = Mock(return_value=cursor)
        cm.__exit__ = Mock(return_value=None)
        return cm, cursor

    def _make_conn(self, cursor: Mock) -> Mock:
        cm, _ = cursor if isinstance(cursor, tuple) else (None, cursor)
        conn = Mock()
        conn.cursor = Mock(return_value=cursor)
        return conn

    def test_serializes_choices_as_jsonb(self) -> None:
        from psycopg.types.json import Json
        cursor = Mock()
        cursor_cm = Mock()
        cursor_cm.__enter__ = Mock(return_value=cursor)
        cursor_cm.__exit__ = Mock(return_value=None)
        conn = Mock()
        conn.cursor = Mock(return_value=cursor_cm)

        spec = _make_test_draw_spec()
        upsert_draw_spec(conn, spec)

        assert cursor.execute.called
        args = cursor.execute.call_args[0][1]  # positional param tuple
        # choices_json is at index 7 in the SQL param list
        # (state, hunt_code, year, schema_version, quota, point_system,
        #  residency_cap, choices, pools, draw_phase, successor, deadline, params, source)
        choices_param = args[7]
        assert isinstance(choices_param, Json), (
            f"Expected choices to be wrapped in Json; got {type(choices_param)}"
        )

    def test_serializes_pools_as_jsonb_array(self) -> None:
        from psycopg.types.json import Json
        cursor = Mock()
        cursor_cm = Mock()
        cursor_cm.__enter__ = Mock(return_value=cursor)
        cursor_cm.__exit__ = Mock(return_value=None)
        conn = Mock()
        conn.cursor = Mock(return_value=cursor_cm)

        spec = _make_test_draw_spec()
        upsert_draw_spec(conn, spec)

        args = cursor.execute.call_args[0][1]
        pools_param = args[8]  # pools is at index 8
        assert isinstance(pools_param, Json), (
            f"Expected pools to be wrapped in Json; got {type(pools_param)}"
        )

    def test_nullable_point_system_serializes_as_none(self) -> None:
        cursor = Mock()
        cursor_cm = Mock()
        cursor_cm.__enter__ = Mock(return_value=cursor)
        cursor_cm.__exit__ = Mock(return_value=None)
        conn = Mock()
        conn.cursor = Mock(return_value=cursor_cm)

        spec = _make_test_draw_spec(point_system=None)
        upsert_draw_spec(conn, spec)

        args = cursor.execute.call_args[0][1]
        point_system_param = args[5]  # index 5
        assert point_system_param is None, (
            f"None point_system must serialize as Python None (SQL NULL); got {point_system_param!r}"
        )

    def test_nullable_residency_cap_serializes_as_none(self) -> None:
        cursor = Mock()
        cursor_cm = Mock()
        cursor_cm.__enter__ = Mock(return_value=cursor)
        cursor_cm.__exit__ = Mock(return_value=None)
        conn = Mock()
        conn.cursor = Mock(return_value=cursor_cm)

        spec = _make_test_draw_spec(residency_cap=None)
        upsert_draw_spec(conn, spec)

        args = cursor.execute.call_args[0][1]
        residency_cap_param = args[6]  # index 6
        assert residency_cap_param is None

    def test_nullable_successor_key_serializes_as_none(self) -> None:
        cursor = Mock()
        cursor_cm = Mock()
        cursor_cm.__enter__ = Mock(return_value=cursor)
        cursor_cm.__exit__ = Mock(return_value=None)
        conn = Mock()
        conn.cursor = Mock(return_value=cursor_cm)

        spec = _make_test_draw_spec(successor_hunt_code_key=None)
        upsert_draw_spec(conn, spec)

        args = cursor.execute.call_args[0][1]
        successor_param = args[10]  # index 10
        assert successor_param is None

    def test_parameters_none_serializes_as_none(self) -> None:
        cursor = Mock()
        cursor_cm = Mock()
        cursor_cm.__enter__ = Mock(return_value=cursor)
        cursor_cm.__exit__ = Mock(return_value=None)
        conn = Mock()
        conn.cursor = Mock(return_value=cursor_cm)

        spec = _make_test_draw_spec(parameters=None)
        upsert_draw_spec(conn, spec)

        args = cursor.execute.call_args[0][1]
        params_param = args[12]  # index 12
        assert params_param is None, (
            f"None parameters must serialize as Python None (SQL NULL); got {params_param!r}"
        )

    def test_no_commit_called(self) -> None:
        cursor = Mock()
        cursor_cm = Mock()
        cursor_cm.__enter__ = Mock(return_value=cursor)
        cursor_cm.__exit__ = Mock(return_value=None)
        conn = Mock()
        conn.cursor = Mock(return_value=cursor_cm)

        spec = _make_test_draw_spec()
        upsert_draw_spec(conn, spec)

        conn.commit.assert_not_called()

    def test_parameters_with_non_json_stdlib_values_serializes_safely(self) -> None:
        """A state adapter may legitimately write date/UUID/Decimal into the
        ADR-012 escape-hatch parameters dict. The serializer must convert these
        to JSON-safe forms BEFORE wrapping in Json — raw json.dumps would raise
        TypeError at cursor.execute time, but we want the values to round-trip
        as strings via Pydantic's TypeAdapter dump_python(mode='json').

        Without the TypeAdapter fix, this test would fail with TypeError at
        execute time when the mocked cursor tried to serialize the Json wrapper.
        With the fix, the wrapped value is already a JSON-safe dict.
        """
        import datetime as _dt
        import json as _json
        from decimal import Decimal
        from uuid import UUID

        cursor = Mock()
        cursor_cm = Mock()
        cursor_cm.__enter__ = Mock(return_value=cursor)
        cursor_cm.__exit__ = Mock(return_value=None)
        conn = Mock()
        conn.cursor = Mock(return_value=cursor_cm)

        exotic_params: dict[str, object] = {
            "some_date": _dt.date(2026, 7, 15),
            "some_uuid": UUID("12345678-1234-5678-1234-567812345678"),
            "some_decimal": Decimal("3.14"),
            "some_str": "plain",
            "some_int": 42,
        }
        spec = _make_test_draw_spec(parameters=exotic_params)
        upsert_draw_spec(conn, spec)

        args = cursor.execute.call_args[0][1]
        params_param = args[12]
        # Wrapped in Json; the inner value must already be JSON-serializable
        assert params_param is not None, "exotic parameters must not become SQL NULL"
        # Json.adapted attribute holds the wrapped Python value
        wrapped = getattr(params_param, "obj", None) or getattr(params_param, "adapted", None)
        assert wrapped is not None, (
            "could not extract wrapped value from psycopg Json instance "
            f"(attrs: {dir(params_param)})"
        )
        # Round-trip via stdlib json.dumps — would raise TypeError without the fix
        roundtripped = _json.dumps(wrapped)
        decoded = _json.loads(roundtripped)
        assert decoded["some_date"] == "2026-07-15", (
            f"date must serialize as ISO string; got {decoded.get('some_date')!r}"
        )
        assert decoded["some_uuid"] == "12345678-1234-5678-1234-567812345678", (
            f"UUID must serialize as canonical string; got {decoded.get('some_uuid')!r}"
        )
        # Decimal serializes as either string or float depending on adapter mode;
        # accept either, just confirm it survived without TypeError
        assert "some_decimal" in decoded
        assert decoded["some_str"] == "plain"
        assert decoded["some_int"] == 42


class TestUpdateLicenseTagDrawSpecKey:
    def test_rowcount_zero_raises_runtimeerror(self) -> None:
        cursor = Mock()
        cursor.rowcount = 0
        cursor_cm = Mock()
        cursor_cm.__enter__ = Mock(return_value=cursor)
        cursor_cm.__exit__ = Mock(return_value=None)
        conn = Mock()
        conn.cursor = Mock(return_value=cursor_cm)

        key = DrawSpecKey(state="US-MT", hunt_code="Deer B License: 262-50", year=2026)
        with pytest.raises(RuntimeError) as exc_info:
            update_license_tag_draw_spec_key(conn, "some-tag-id", key)
        assert "some-tag-id" in str(exc_info.value), (
            "RuntimeError message must mention the license_tag_id for triage"
        )

    def test_rowcount_one_succeeds_silently(self) -> None:
        cursor = Mock()
        cursor.rowcount = 1
        cursor_cm = Mock()
        cursor_cm.__enter__ = Mock(return_value=cursor)
        cursor_cm.__exit__ = Mock(return_value=None)
        conn = Mock()
        conn.cursor = Mock(return_value=cursor_cm)

        key = DrawSpecKey(state="US-MT", hunt_code="Deer B License: 262-50", year=2026)
        # Should not raise
        update_license_tag_draw_spec_key(conn, "some-tag-id", key)

    def test_no_commit_called(self) -> None:
        cursor = Mock()
        cursor.rowcount = 1
        cursor_cm = Mock()
        cursor_cm.__enter__ = Mock(return_value=cursor)
        cursor_cm.__exit__ = Mock(return_value=None)
        conn = Mock()
        conn.cursor = Mock(return_value=cursor_cm)

        key = DrawSpecKey(state="US-MT", hunt_code="Deer B License: 262-50", year=2026)
        update_license_tag_draw_spec_key(conn, "some-tag-id", key)
        conn.commit.assert_not_called()

    def test_serializes_key_as_jsonb(self) -> None:
        from psycopg.types.json import Json
        cursor = Mock()
        cursor.rowcount = 1
        cursor_cm = Mock()
        cursor_cm.__enter__ = Mock(return_value=cursor)
        cursor_cm.__exit__ = Mock(return_value=None)
        conn = Mock()
        conn.cursor = Mock(return_value=cursor_cm)

        key = DrawSpecKey(state="US-MT", hunt_code="Deer B License: 262-50", year=2026)
        update_license_tag_draw_spec_key(conn, "some-tag-id", key)

        args = cursor.execute.call_args[0][1]
        key_param = args[0]
        assert isinstance(key_param, Json), (
            f"DrawSpecKey must be wrapped in Json for jsonb column; got {type(key_param)}"
        )


# ---------------------------------------------------------------------------
# TestNoLibImports
# ---------------------------------------------------------------------------


class TestNoLibImports:
    """State-agnostic-clean AST guard.

    ``load_draw_specs.py`` is a state adapter — it may import from
    ``ingestion.lib.*`` (shared library) only via the documented public API.
    Private names (prefixed ``_``) must not be imported from ``ingestion.lib.db``
    so that the canonical write-path contract is not bypassed.
    """

    def test_load_draw_specs_only_uses_lib_db_public_api(self) -> None:
        """AST-walk load_draw_specs.py: all `from ingestion.lib.db import` must use
        only public helpers (connect, upsert_*, update_*). No _PRIVATE names.
        """
        source_path = Path(lds.__file__)
        source = source_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "ingestion.lib.db":
                    for alias in node.names:
                        name = alias.name
                        if name.startswith("_"):
                            violations.append(
                                f"line {node.lineno}: private name {name!r} "
                                f"imported from ingestion.lib.db"
                            )

        assert not violations, (
            "load_draw_specs.py leaks private ingestion.lib.db names:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )
