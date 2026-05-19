"""Unit tests for ``ingestion/states/montana/load_seasons_and_licenses.py``.

Coverage:
- TestParseWindow              — DEA/bear window string parsing into date tuples
- TestParseQuotaRange          — quota-range string → (int, int) | None
- TestLicenseCodeSlug          — license code → stable URL-safe slug
- TestIdConstructors            — deterministic id construction functions
- TestBuildDeaSeasonDefinitions — DEA section → SeasonDefinition dedup + verbatim
- TestBuildDeaLicenseTags       — DEA rows → LicenseTag kind heuristic + statewide
- TestBuildDeaLinkRows          — license_season + regulation_season + regulation_license
- TestDeerSpeciesFanOut         — deer × 2 fan-out in link-row builders
- TestBuildBearSeasonDefinitions— closure_predicate attachment + 8-BMU lock
- TestBuildBearLicenseTags      — bear-specific LicenseTag shape assertions
- TestStatewideOverlay          — 900-20 antelope statewide row end-to-end
- TestCountGuards               — five count-guard functions, in-band + both error cases
- TestMain                     — dry-run smoke test + count verification

The editable install adds ``ingestion/`` to sys.path so ``states.montana.*``
is directly importable, the same way every sibling adapter test does it.
"""

from __future__ import annotations

import datetime as dt
import logging

import pytest

from ingestion.lib.schema import SourceCitation
from states.montana.load_seasons_and_licenses import (
    _assert_license_season_count_within_guard,
    _assert_license_tag_count_within_guard,
    _assert_regulation_license_count_within_guard,
    _assert_regulation_season_count_within_guard,
    _assert_season_definition_count_within_guard,
    _bear_license_tag_id,
    _bear_season_definition_id,
    _build_bear_license_season_links,
    _build_bear_license_tags,
    _build_bear_regulation_license_links,
    _build_bear_regulation_season_links,
    _build_bear_season_definitions,
    _build_dea_license_season_links,
    _build_dea_license_tags,
    _build_dea_regulation_license_links,
    _build_dea_regulation_season_links,
    _build_dea_season_definitions,
    _license_code_slug,
    _license_tag_id,
    _parse_quota_range,
    _parse_window,
    _row_has_otc,
    _season_definition_id,
    main,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_BASE_PAGE_REF = {
    "bbox": [0, 0, 612, 792],
    "extracted_at": "2026-01-01T00:00:00+00:00",
    "page_num_1based": 1,
    "pdf_filename": "test.pdf",
}


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


@pytest.fixture
def hd170_elk_section() -> dict:
    """Mini DEA section mimicking HD 170 elk's structure for asymmetric-coverage tests."""
    return {
        "hd_number": "170",
        "hd_name": "Flathead River",
        "species_group": "elk",
        "license_year": 2026,
        "page_reference": _BASE_PAGE_REF,
        "verbatim_text": "HD 170 Flathead River elk section verbatim text...",
        "rows": [
            {
                "license_code": "General Elk License",
                "opportunity": "Brow-tined Bull Elk",
                "apply_by": None,
                "quota": None,
                "quota_range": None,
                "season_coverage": {
                    "early_season": False,
                    "archery_only": True,
                    "general": True,
                    "heritage_muzzleloader": True,
                    "late": False,
                },
                "season_windows": {
                    "archery_only": {"window": "Sep 05-Oct 18", "weapon_type_override": "archery"},
                    "general": {"window": "Oct 24-Nov 29", "weapon_type_override": None},
                    "heritage_muzzleloader": {"window": "Dec 12-Dec 20", "weapon_type_override": "muzzleloader"},
                },
                "weapon_types": ["any_legal_weapon"],
                "extras": "See DEA booklet for details.",
                "extraction_confidence": "high",
                "page_reference": _BASE_PAGE_REF,
            },
            {
                "license_code": "General Elk License",
                "opportunity": "Brow-tined Bull or Antlerless Elk",
                "apply_by": None,
                "quota": None,
                "quota_range": None,
                "season_coverage": {
                    "early_season": False,
                    "archery_only": False,
                    "general": True,
                    "heritage_muzzleloader": True,
                    "late": False,
                },
                "season_windows": {
                    "general": {"window": "Oct 24-Nov 29", "weapon_type_override": None},
                    "heritage_muzzleloader": {"window": "Dec 12-Dec 20", "weapon_type_override": "muzzleloader"},
                },
                "weapon_types": ["any_legal_weapon"],
                "extras": None,
                "extraction_confidence": "high",
                "page_reference": _BASE_PAGE_REF,
            },
            {
                "license_code": "Elk B License: 170-00",
                "opportunity": "Antlerless Elk",
                "apply_by": None,
                "quota": 50,
                "quota_range": None,
                "season_coverage": {
                    "early_season": False,
                    "archery_only": True,
                    "general": True,
                    "heritage_muzzleloader": False,
                    "late": True,
                },
                "season_windows": {
                    "archery_only": {"window": "Sep 05-Oct 18", "weapon_type_override": "archery"},
                    "general": {"window": "Oct 24-Nov 29", "weapon_type_override": None},
                    "late": {"window": "Nov 30-Jan 01", "weapon_type_override": None},
                },
                "weapon_types": ["any_legal_weapon"],
                "extras": "B-license details.",
                "extraction_confidence": "high",
                "page_reference": _BASE_PAGE_REF,
            },
        ],
    }


@pytest.fixture
def mock_bear_artifact() -> dict:
    """Mini bear artifact with 3 BMUs covering both closure types and a non-closure BMU."""
    base_page_ref = {
        "bbox": [0, 0, 612, 792],
        "extracted_at": "2026-01-01T00:00:00+00:00",
        "page_num_1based": 7,
        "pdf_filename": "bear.pdf",
    }
    return {
        "state": "US-MT",
        "species_group": "black_bear",
        "license_year": 2026,
        "schema_version": 2,
        "extracted_at": "2026-05-08T00:21:59.830109+00:00",
        "sources": [
            {
                "id": "mt-fwp-black-bear-2026-booklet",
                "agency": "Montana FWP",
                "title": "Black Bear 2026",
                "url": "https://example.com/bear.pdf",
                "publication_date": "2026-04-27",
                "document_type": "annual_regulations",
            },
            {
                "id": "mt-fwp-black-bear-2026-correction-2026-03-18",
                "agency": "Montana FWP",
                "title": "Black Bear Correction",
                "url": "https://example.com/bear-corr.pdf",
                "publication_date": "2026-03-18",
                "document_type": "correction",
            },
        ],
        "rows": [
            # BMU 411 — quota-closure + female-subquota
            {
                "bmu_number": 411,
                "hd_region": "R4",
                "opportunity": "Either-sex",
                "general_season": "Sep 15-Nov 29",
                "archery_only_season": "Sep 05-Sep 14",
                "spring_season": "Apr 15-Jun 15",
                "hound_training_season": None,
                "hound_nr_license": "411-00",
                "hound_nr_max": 1,
                "fall_quota": {"count": 4, "kind": "female_subquota", "verbatim": "= 4 Female"},
                "spring_quota": {"count": 2, "kind": "female_subquota", "verbatim": "= 2 Female"},
                "page_reference": base_page_ref,
                "verbatim_text": "BMU 411 verbatim",
                "extraction_confidence": "medium",
                "source_id": "mt-fwp-black-bear-2026-correction-2026-03-18",
                "source_publication_date": "2026-03-18",
                "applied_correction": True,
                "supersedes": "mt-fwp-black-bear-2026-booklet",
            },
            # BMU 300 — sex-threshold spring closure
            {
                "bmu_number": 300,
                "hd_region": "R1",
                "opportunity": "Either-sex",
                "general_season": "Sep 15-Nov 29",
                "archery_only_season": "Sep 05-Sep 14",
                "spring_season": "Apr 15-Jun 15",
                "hound_training_season": None,
                "hound_nr_license": None,
                "hound_nr_max": None,
                "fall_quota": {"count": None, "kind": None, "verbatim": "-"},
                "spring_quota": {"count": None, "kind": None, "verbatim": "-"},
                "page_reference": base_page_ref,
                "verbatim_text": "BMU 300 verbatim",
                "extraction_confidence": "medium",
                "source_id": "mt-fwp-black-bear-2026-correction-2026-03-18",
                "source_publication_date": "2026-03-18",
                "applied_correction": True,
                "supersedes": "mt-fwp-black-bear-2026-booklet",
            },
            # BMU 100 — no closure
            {
                "bmu_number": 100,
                "hd_region": "R1",
                "opportunity": "Either-sex",
                "general_season": "Sep 15-Nov 29",
                "archery_only_season": "Sep 05-Sep 14",
                "spring_season": "Apr 15-Jun 15",
                "hound_training_season": None,
                "hound_nr_license": None,
                "hound_nr_max": None,
                "fall_quota": {"count": None, "kind": None, "verbatim": "-"},
                "spring_quota": {"count": None, "kind": None, "verbatim": "-"},
                "page_reference": base_page_ref,
                "verbatim_text": "BMU 100 verbatim",
                "extraction_confidence": "medium",
                "source_id": "mt-fwp-black-bear-2026-correction-2026-03-18",
                "source_publication_date": "2026-03-18",
                "applied_correction": True,
                "supersedes": "mt-fwp-black-bear-2026-booklet",
            },
        ],
        "closures": [
            {
                "bmu_numbers": [300, 301, 319, 580],
                "kind": "sex_threshold",
                "threshold_percent": 37.0,
                "threshold_sex": "female",
                "notification_channel": "agency_website",
                "observation_channel": "mandatory_reporting",
                "verbatim_rule": "Spring Season Closure prose...",
                "page_reference": base_page_ref,
                "source_id": "mt-fwp-black-bear-2026-booklet",
                "source_publication_date": "2026-04-27",
                "extraction_confidence": "medium",
            },
            {
                "bmu_numbers": [411, 420, 440, 450, 510, 520, 600, 700],
                "kind": "quota_threshold",
                "threshold_percent": None,
                "threshold_sex": None,
                "notification_channel": "agency_phone",
                "observation_channel": "mandatory_reporting",
                "verbatim_rule": "Quota-closure prose...",
                "page_reference": base_page_ref,
                "source_id": "mt-fwp-black-bear-2026-booklet",
                "source_publication_date": "2026-04-27",
                "extraction_confidence": "medium",
            },
        ],
        "reporting_obligations": [],
    }


# ---------------------------------------------------------------------------
# TestParseWindow
# ---------------------------------------------------------------------------


class TestParseWindow:
    def test_dotless_format(self) -> None:
        opens, closes = _parse_window("Sep 05-Oct 18", 2026)
        assert opens == dt.date(2026, 9, 5)
        assert closes == dt.date(2026, 10, 18)

    def test_dotted_format(self) -> None:
        opens, closes = _parse_window("Aug. 15-Nov. 08", 2026)
        assert opens == dt.date(2026, 8, 15)
        assert closes == dt.date(2026, 11, 8)

    def test_bear_newline_format(self) -> None:
        opens, closes = _parse_window("Sep.\n15-Nov.\n29", 2026)
        assert opens == dt.date(2026, 9, 15)
        assert closes == dt.date(2026, 11, 29)

    def test_year_wrap(self) -> None:
        # Nov 30 - Jan 01 crosses year boundary
        opens, closes = _parse_window("Nov 30-Jan 01", 2026)
        assert opens == dt.date(2026, 11, 30)
        assert closes == dt.date(2027, 1, 1)

    def test_sept_4letter_abbreviation(self) -> None:
        # FWP antelope tables use "Sept." (4-letter)
        opens, closes = _parse_window("Sept. 05-Oct. 09", 2026)
        assert opens == dt.date(2026, 9, 5)
        assert closes == dt.date(2026, 10, 9)

    def test_malformed_input_raises_value_error(self) -> None:
        with pytest.raises(ValueError):
            _parse_window("not a date", 2026)

    def test_general_season_no_year_wrap(self) -> None:
        opens, closes = _parse_window("Oct 24-Nov 29", 2026)
        assert opens == dt.date(2026, 10, 24)
        assert closes == dt.date(2026, 11, 29)


# ---------------------------------------------------------------------------
# TestParseQuotaRange
# ---------------------------------------------------------------------------


class TestParseQuotaRange:
    def test_comma_thousands_separator(self) -> None:
        result = _parse_quota_range("1-7,500")
        assert result == (1, 7500)

    def test_none_input_returns_none(self) -> None:
        assert _parse_quota_range(None) is None

    def test_whitespace_only_returns_none(self) -> None:
        assert _parse_quota_range("  ") is None

    def test_multi_dash_raises(self) -> None:
        with pytest.raises(ValueError):
            _parse_quota_range("1-2-3")

    def test_valid_simple_range(self) -> None:
        assert _parse_quota_range("50-100") == (50, 100)

    def test_empty_string_returns_none(self) -> None:
        assert _parse_quota_range("") is None


# ---------------------------------------------------------------------------
# TestLicenseCodeSlug
# ---------------------------------------------------------------------------


class TestLicenseCodeSlug:
    def test_general_elk(self) -> None:
        assert _license_code_slug("General Elk License") == "general"

    def test_general_deer(self) -> None:
        assert _license_code_slug("General Deer License") == "general"

    def test_general_antelope(self) -> None:
        assert _license_code_slug("General Antelope License") == "general"

    def test_elk_b_license(self) -> None:
        assert _license_code_slug("Elk B License: 124-00") == "elk-b-124-00"

    def test_deer_b_license(self) -> None:
        assert _license_code_slug("Deer B License: 262-50") == "deer-b-262-50"

    def test_antelope_license_900_20(self) -> None:
        assert _license_code_slug("Antelope License: 900-20") == "antelope-900-20"

    def test_antelope_license_471_20(self) -> None:
        assert _license_code_slug("Antelope License: 471-20") == "antelope-471-20"

    def test_deer_permit(self) -> None:
        assert _license_code_slug("Deer Permit: 262-51") == "deer-permit-262-51"

    def test_unrecognized_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="unrecognized license_code format"):
            _license_code_slug("Random Garbage Code")


# ---------------------------------------------------------------------------
# TestIdConstructors
# ---------------------------------------------------------------------------


class TestIdConstructors:
    def test_season_definition_id_per_hd_general(self) -> None:
        assert _season_definition_id("elk", "262", "general") == "MT-HD-262-elk-general-2026"

    def test_season_definition_id_statewide(self) -> None:
        assert _season_definition_id("antelope", "STATEWIDE", "general") == "MT-STATEWIDE-antelope-general-2026"

    def test_season_definition_id_archery_only(self) -> None:
        # archery_only (underscore) → archery-only (hyphen) in slug
        assert _season_definition_id("elk", "262", "archery_only") == "MT-HD-262-elk-archery-only-2026"

    def test_license_tag_id_b_license(self) -> None:
        result = _license_tag_id("elk", "262", "Elk B License: 262-50")
        assert result == "MT-HD-262-elk-elk-b-262-50-2026"

    def test_license_tag_id_disambiguates_same_numeric_across_species_in_section(self) -> None:
        """Cubic P1 regression lock (2026-05-16): when a deer section cross-
        lists a Deer B and Elk B license sharing the same numeric code, the
        slug-with-prefix produces DISTINCT license_tag ids.  Without the
        prefix, 6 collisions occur in the live V1 artifact (deer sections
        555 / 410 / 455 / 630 / 700 with cross-listed Elk B variants).
        """
        deer_b = _license_tag_id("deer", "555", "Deer B License: 005-00")
        elk_b = _license_tag_id("deer", "555", "Elk B License: 005-00")
        assert deer_b == "MT-HD-555-deer-deer-b-005-00-2026"
        assert elk_b == "MT-HD-555-deer-elk-b-005-00-2026"
        assert deer_b != elk_b

    def test_bear_season_definition_id_general(self) -> None:
        assert _bear_season_definition_id(411, "general") == "MT-BMU-411-bear-general-2026"

    def test_bear_season_definition_id_archery_only(self) -> None:
        assert _bear_season_definition_id(411, "archery-only") == "MT-BMU-411-bear-archery-only-2026"

    def test_bear_license_tag_id(self) -> None:
        assert _bear_license_tag_id(411) == "MT-BMU-411-bear-2026"

    def test_season_definition_id_heritage_muzzleloader(self) -> None:
        result = _season_definition_id("elk", "170", "heritage_muzzleloader")
        assert result == "MT-HD-170-elk-heritage-muzzleloader-2026"


# ---------------------------------------------------------------------------
# TestBuildDeaSeasonDefinitions
# ---------------------------------------------------------------------------


class TestBuildDeaSeasonDefinitions:
    def test_hd170_elk_yields_4_unique_season_definitions(
        self, hd170_elk_section: dict, mock_dea_citation: SourceCitation
    ) -> None:
        defs = _build_dea_season_definitions([hd170_elk_section], mock_dea_citation)
        assert len(defs) == 4

    def test_hd170_elk_ids_match_expected(
        self, hd170_elk_section: dict, mock_dea_citation: SourceCitation
    ) -> None:
        defs = _build_dea_season_definitions([hd170_elk_section], mock_dea_citation)
        ids = {d.id for d in defs}
        assert ids == {
            "MT-HD-170-elk-archery-only-2026",
            "MT-HD-170-elk-general-2026",
            "MT-HD-170-elk-heritage-muzzleloader-2026",
            "MT-HD-170-elk-late-2026",
        }

    def test_archery_only_weapon_type(
        self, hd170_elk_section: dict, mock_dea_citation: SourceCitation
    ) -> None:
        defs = _build_dea_season_definitions([hd170_elk_section], mock_dea_citation)
        archery = next(d for d in defs if d.id == "MT-HD-170-elk-archery-only-2026")
        assert archery.weapon_type == "archery"

    def test_muzzleloader_weapon_type(
        self, hd170_elk_section: dict, mock_dea_citation: SourceCitation
    ) -> None:
        defs = _build_dea_season_definitions([hd170_elk_section], mock_dea_citation)
        muzz = next(d for d in defs if d.id == "MT-HD-170-elk-heritage-muzzleloader-2026")
        assert muzz.weapon_type == "muzzleloader"

    def test_general_season_weapon_type_is_none(
        self, hd170_elk_section: dict, mock_dea_citation: SourceCitation
    ) -> None:
        defs = _build_dea_season_definitions([hd170_elk_section], mock_dea_citation)
        general = next(d for d in defs if d.id == "MT-HD-170-elk-general-2026")
        assert general.weapon_type is None

    def test_duplicate_general_elk_license_rows_produce_one_season_definition(
        self, hd170_elk_section: dict, mock_dea_citation: SourceCitation
    ) -> None:
        # Both row 0 and row 1 share "General Elk License" covering general + HM.
        # The dedup should yield exactly ONE "general" season_definition (first-wins).
        defs = _build_dea_season_definitions([hd170_elk_section], mock_dea_citation)
        general_defs = [d for d in defs if d.id == "MT-HD-170-elk-general-2026"]
        assert len(general_defs) == 1

    def test_verbatim_rule_prefers_general_row_extras(
        self, hd170_elk_section: dict, mock_dea_citation: SourceCitation
    ) -> None:
        # Row 0 (General Elk License) has extras="See DEA booklet for details."
        # Row 1 (General Elk License) has extras=None.
        # Row 2 (Elk B License) has extras="B-license details."
        # For the "general" season, preference is General-row extras → row 0 wins.
        defs = _build_dea_season_definitions([hd170_elk_section], mock_dea_citation)
        general = next(d for d in defs if d.id == "MT-HD-170-elk-general-2026")
        assert general.verbatim_rule == "See DEA booklet for details."

    def test_verbatim_rule_late_falls_back_to_b_license_extras(
        self, hd170_elk_section: dict, mock_dea_citation: SourceCitation
    ) -> None:
        # "late" season is only in row 2 (Elk B License) → fallback to any-match.
        defs = _build_dea_season_definitions([hd170_elk_section], mock_dea_citation)
        late = next(d for d in defs if d.id == "MT-HD-170-elk-late-2026")
        assert late.verbatim_rule == "B-license details."

    def test_year_wrap_parsed_correctly(
        self, hd170_elk_section: dict, mock_dea_citation: SourceCitation
    ) -> None:
        defs = _build_dea_season_definitions([hd170_elk_section], mock_dea_citation)
        late = next(d for d in defs if d.id == "MT-HD-170-elk-late-2026")
        assert late.closes == dt.date(2027, 1, 1)

    def test_verbatim_rule_falls_back_to_section_verbatim_text_when_all_extras_null(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        """Branch 3 of _select_season_verbatim_rule: all rows covering the
        season have extras=None → fall back to section verbatim_text.
        """
        base_page_ref = {
            "bbox": [0, 0, 612, 792],
            "extracted_at": "2026-01-01T00:00:00+00:00",
            "page_num_1based": 1,
            "pdf_filename": "test.pdf",
        }
        section = {
            "hd_number": "999",
            "hd_name": "Test",
            "species_group": "elk",
            "license_year": 2026,
            "page_reference": base_page_ref,
            "verbatim_text": "FALLBACK SECTION VERBATIM TEXT",
            "rows": [
                {
                    "license_code": "General Elk License",
                    "opportunity": "Test",
                    "apply_by": None,
                    "quota": None,
                    "quota_range": None,
                    "season_coverage": {
                        "early_season": False, "archery_only": False,
                        "general": True, "heritage_muzzleloader": False,
                        "late": False,
                    },
                    "season_windows": {
                        "general": {"window": "Oct 24-Nov 29", "weapon_type_override": None},
                    },
                    "weapon_types": ["any_legal_weapon"],
                    "extras": None,  # forces fallback to branch 2
                    "extraction_confidence": "high",
                    "page_reference": base_page_ref,
                },
            ],
        }
        defs = _build_dea_season_definitions([section], mock_dea_citation)
        assert len(defs) == 1
        assert defs[0].verbatim_rule == "FALLBACK SECTION VERBATIM TEXT"


# ---------------------------------------------------------------------------
# TestBuildDeaLicenseTags
# ---------------------------------------------------------------------------


class TestBuildDeaLicenseTags:
    def test_general_elk_kind_is_general(
        self, hd170_elk_section: dict, mock_dea_citation: SourceCitation
    ) -> None:
        tags = _build_dea_license_tags([hd170_elk_section], mock_dea_citation)
        general_tags = [t for t in tags if t.license_code == "General Elk License"]
        assert all(t.kind == "general" for t in general_tags)

    def test_b_license_kind_is_limited_draw(
        self, hd170_elk_section: dict, mock_dea_citation: SourceCitation
    ) -> None:
        tags = _build_dea_license_tags([hd170_elk_section], mock_dea_citation)
        b_tag = next(t for t in tags if t.license_code == "Elk B License: 170-00")
        assert b_tag.kind == "limited_draw"

    def test_permit_license_kind_is_limited_draw(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        section = {
            "hd_number": "262",
            "hd_name": "Sun River",
            "species_group": "deer",
            "license_year": 2026,
            "page_reference": _BASE_PAGE_REF,
            "verbatim_text": "HD 262 deer",
            "rows": [
                {
                    "license_code": "Deer Permit: 262-51",
                    "opportunity": "Antlerless Deer",
                    "apply_by": None,
                    "quota": 10,
                    "quota_range": None,
                    "season_coverage": {"general": True},
                    "season_windows": {
                        "general": {"window": "Oct 24-Nov 29", "weapon_type_override": None},
                    },
                    "weapon_types": ["any_legal_weapon"],
                    "extras": None,
                    "extraction_confidence": "medium",
                    "page_reference": _BASE_PAGE_REF,
                },
            ],
        }
        tags = _build_dea_license_tags([section], mock_dea_citation)
        assert len(tags) == 1
        assert tags[0].kind == "limited_draw"

    def test_antelope_license_per_hd_kind_is_limited_draw(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        section = {
            "hd_number": "471",
            "hd_name": "HD 471",
            "species_group": "antelope",
            "license_year": 2026,
            "page_reference": _BASE_PAGE_REF,
            "verbatim_text": "antelope",
            "rows": [
                {
                    "license_code": "Antelope License: 471-20",
                    "opportunity": "Either-sex",
                    "apply_by": None,
                    "quota": 50,
                    "quota_range": None,
                    "season_coverage": {"general": True},
                    "season_windows": {
                        "general": {"window": "Oct 24-Nov 09", "weapon_type_override": None},
                    },
                    "weapon_types": ["any_legal_weapon"],
                    "extras": None,
                    "extraction_confidence": "high",
                    "page_reference": _BASE_PAGE_REF,
                },
            ],
        }
        tags = _build_dea_license_tags([section], mock_dea_citation)
        assert tags[0].kind == "limited_draw"

    def test_statewide_antelope_kind_is_statewide(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        section = {
            "hd_number": "STATEWIDE",
            "hd_name": "Statewide",
            "species_group": "antelope",
            "license_year": 2026,
            "page_reference": _BASE_PAGE_REF,
            "verbatim_text": "statewide antelope",
            "rows": [
                {
                    "license_code": "Antelope License: 900-20",
                    "opportunity": "Statewide Antelope",
                    "apply_by": None,
                    "quota": 5600,
                    "quota_range": "1-7,500",
                    "season_coverage": {"archery_only": True, "general": True},
                    "season_windows": {
                        "archery_only": {"window": "Aug. 15-Nov. 08", "weapon_type_override": "archery"},
                        "general": {"window": "Oct 24-Nov 08", "weapon_type_override": None},
                    },
                    "weapon_types": ["archery"],
                    "extras": None,
                    "extraction_confidence": "high",
                    "page_reference": _BASE_PAGE_REF,
                },
            ],
        }
        tags = _build_dea_license_tags([section], mock_dea_citation)
        assert tags[0].kind == "statewide"

    def test_statewide_antelope_weapon_types_passthrough(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        section = {
            "hd_number": "STATEWIDE",
            "hd_name": "Statewide",
            "species_group": "antelope",
            "license_year": 2026,
            "page_reference": _BASE_PAGE_REF,
            "verbatim_text": "statewide antelope",
            "rows": [
                {
                    "license_code": "Antelope License: 900-20",
                    "opportunity": "Statewide Antelope",
                    "apply_by": None,
                    "quota": 5600,
                    "quota_range": "1-7,500",
                    "season_coverage": {"archery_only": True},
                    "season_windows": {
                        "archery_only": {"window": "Aug. 15-Nov. 08", "weapon_type_override": "archery"},
                    },
                    "weapon_types": ["archery"],
                    "extras": None,
                    "extraction_confidence": "high",
                    "page_reference": _BASE_PAGE_REF,
                },
            ],
        }
        tags = _build_dea_license_tags([section], mock_dea_citation)
        assert tags[0].weapon_types == ["archery"]

    def test_statewide_antelope_quota_range_parsed(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        section = {
            "hd_number": "STATEWIDE",
            "hd_name": "Statewide",
            "species_group": "antelope",
            "license_year": 2026,
            "page_reference": _BASE_PAGE_REF,
            "verbatim_text": "statewide antelope",
            "rows": [
                {
                    "license_code": "Antelope License: 900-20",
                    "opportunity": "Statewide Antelope",
                    "apply_by": None,
                    "quota": 5600,
                    "quota_range": "1-7,500",
                    "season_coverage": {"archery_only": True},
                    "season_windows": {
                        "archery_only": {"window": "Aug. 15-Nov. 08", "weapon_type_override": "archery"},
                    },
                    "weapon_types": ["archery"],
                    "extras": None,
                    "extraction_confidence": "high",
                    "page_reference": _BASE_PAGE_REF,
                },
            ],
        }
        tags = _build_dea_license_tags([section], mock_dea_citation)
        assert tags[0].quota_range == (1, 7500)

    def test_gibberish_code_raises_runtime_error(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        section = {
            "hd_number": "100",
            "hd_name": "Test HD",
            "species_group": "elk",
            "license_year": 2026,
            "page_reference": _BASE_PAGE_REF,
            "verbatim_text": "text",
            "rows": [
                {
                    "license_code": "Gibberish Code That Matches Nothing",
                    "opportunity": "Some Opportunity",
                    "apply_by": None,
                    "quota": None,
                    "quota_range": None,
                    "season_coverage": {"general": True},
                    "season_windows": {
                        "general": {"window": "Oct 24-Nov 29", "weapon_type_override": None},
                    },
                    "weapon_types": ["any_legal_weapon"],
                    "extras": None,
                    "extraction_confidence": "high",
                    "page_reference": _BASE_PAGE_REF,
                },
            ],
        }
        with pytest.raises(RuntimeError, match="unrecognized license_code kind"):
            _build_dea_license_tags([section], mock_dea_citation)

    def test_duplicate_general_elk_emits_two_tags_not_deduplicated(
        self, hd170_elk_section: dict, mock_dea_citation: SourceCitation
    ) -> None:
        # HD 170 elk has two "General Elk License" rows — builder emits BOTH.
        # Dedup is the DB upsert's job, not the builder's.
        tags = _build_dea_license_tags([hd170_elk_section], mock_dea_citation)
        general_tags = [t for t in tags if t.license_code == "General Elk License"]
        assert len(general_tags) == 2
        # Both carry the same id (identical license_code, species, hd)
        assert general_tags[0].id == general_tags[1].id

    def test_total_tags_count_for_hd170_elk(
        self, hd170_elk_section: dict, mock_dea_citation: SourceCitation
    ) -> None:
        # 3 rows → 3 tags (2 General + 1 B License)
        tags = _build_dea_license_tags([hd170_elk_section], mock_dea_citation)
        assert len(tags) == 3

    def test_dea_license_tags_have_draw_spec_key_none(self, hd170_elk_section: dict, mock_dea_citation: SourceCitation) -> None:
        """ADR-012 / spec line 668-670: license_tag.draw_spec_key is NULL on
        every row written by S03.7; S03.8 backfills for limited-draw rows.
        """
        tags = _build_dea_license_tags([hd170_elk_section], mock_dea_citation)
        assert tags  # fixture sanity
        for tag in tags:
            assert tag.draw_spec_key is None, (
                f"license_tag {tag.id} has draw_spec_key={tag.draw_spec_key}; "
                f"S03.7 must leave this NULL for S03.8 to backfill"
            )


# ---------------------------------------------------------------------------
# TestBuildDeaLinkRows
# ---------------------------------------------------------------------------


class TestBuildDeaLinkRows:
    def test_license_season_asymmetric_coverage_m1_criterion(
        self, hd170_elk_section: dict
    ) -> None:
        """M1 success criterion #2: A and B licenses reference different season sets."""
        links = _build_dea_license_season_links([hd170_elk_section])

        # Build per-license-tag coverage sets
        general_tag_id = _license_tag_id("elk", "170", "General Elk License")
        b_tag_id = _license_tag_id("elk", "170", "Elk B License: 170-00")

        general_seasons = {
            lk.season_definition_id for lk in links if lk.license_tag_id == general_tag_id
        }
        b_seasons = {
            lk.season_definition_id for lk in links if lk.license_tag_id == b_tag_id
        }

        # General Elk License row 0: archery_only + general + heritage_muzzleloader
        # General Elk License row 1: general + heritage_muzzleloader
        # Union of both: archery_only + general + heritage_muzzleloader
        assert general_seasons == {
            "MT-HD-170-elk-archery-only-2026",
            "MT-HD-170-elk-general-2026",
            "MT-HD-170-elk-heritage-muzzleloader-2026",
        }

        # Elk B License: 170-00 row 2: archery_only + general + late
        assert b_seasons == {
            "MT-HD-170-elk-archery-only-2026",
            "MT-HD-170-elk-general-2026",
            "MT-HD-170-elk-late-2026",
        }

        # Asymmetric difference: A-only = heritage-muzzleloader, B-only = late
        a_only = general_seasons - b_seasons
        b_only = b_seasons - general_seasons
        assert a_only == {"MT-HD-170-elk-heritage-muzzleloader-2026"}
        assert b_only == {"MT-HD-170-elk-late-2026"}

    def test_regulation_season_links_elk_hd170(
        self, hd170_elk_section: dict
    ) -> None:
        links = _build_dea_regulation_season_links([hd170_elk_section])
        # elk has no fan-out (1 species) × 4 unique seasons = 4 rows
        assert len(links) == 4
        species_groups = {lk.species_group for lk in links}
        assert species_groups == {"elk"}

    def test_regulation_license_links_elk_hd170(
        self, hd170_elk_section: dict
    ) -> None:
        links = _build_dea_regulation_license_links([hd170_elk_section])
        # elk has no fan-out (1 species); 3 artifact rows → 3 links
        assert len(links) == 3
        species_groups = {lk.species_group for lk in links}
        assert species_groups == {"elk"}

    def test_season_coverage_false_drift_skipped_across_three_builders(
        self, mock_dea_citation: SourceCitation, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Drift guard: when season_windows has an entry but season_coverage[key]
        is False, all three DEA builders that iterate season_windows MUST treat
        season_coverage as the source of truth and skip the entry (with a WARN).

        Discovery confirmed the invariant (season_windows keys ≡ season_coverage
        trues) holds for the V1 artifact, so this branch is normally unreachable.
        It exists as a defense against S03.3 extraction regression.
        """
        section = {
            "hd_number": "999",
            "hd_name": "Drift",
            "species_group": "elk",
            "license_year": 2026,
            "page_reference": _BASE_PAGE_REF,
            "verbatim_text": "Drift section",
            "rows": [
                {
                    "license_code": "General Elk License",
                    "opportunity": "Test",
                    "apply_by": None,
                    "quota": None,
                    "quota_range": None,
                    # season_coverage says general=True, archery_only=False, ...
                    "season_coverage": {
                        "early_season": False,
                        "archery_only": False,  # NOT covered
                        "general": True,
                        "heritage_muzzleloader": False,
                        "late": False,
                    },
                    # season_windows has archery_only AND general — drift.
                    "season_windows": {
                        "archery_only": {"window": "Sep 05-Oct 18", "weapon_type_override": "archery"},
                        "general": {"window": "Oct 24-Nov 29", "weapon_type_override": None},
                    },
                    "weapon_types": ["any_legal_weapon"],
                    "extras": None,
                    "extraction_confidence": "high",
                    "page_reference": _BASE_PAGE_REF,
                },
            ],
        }

        with caplog.at_level(logging.WARNING):
            defs = _build_dea_season_definitions([section], mock_dea_citation)
            ls_links = _build_dea_license_season_links([section])
            rs_links = _build_dea_regulation_season_links([section])

        # All three builders must respect season_coverage truth: only `general`
        # is covered; the archery_only entry in season_windows is drift and must
        # be skipped.
        assert [d.id for d in defs] == ["MT-HD-999-elk-general-2026"]
        assert [lk.season_definition_id for lk in ls_links] == ["MT-HD-999-elk-general-2026"]
        assert [lk.season_definition_id for lk in rs_links] == ["MT-HD-999-elk-general-2026"]

        # Drift WARNs surfaced (one per builder × one per drifted key).
        drift_warnings = [
            r for r in caplog.records
            if "season_coverage[" in r.getMessage() and "=False" in r.getMessage()
        ]
        assert len(drift_warnings) >= 2  # at minimum: defs builder + ls builder
        # Static set comprehension in rs builder filters silently without WARN —
        # the defs + ls WARNs are the surfaced signal.


# ---------------------------------------------------------------------------
# TestDeerSpeciesFanOut
# ---------------------------------------------------------------------------


class TestDeerSpeciesFanOut:
    @pytest.fixture
    def hd124_deer_section(self) -> dict:
        return {
            "hd_number": "124",
            "hd_name": "Blackfoot",
            "species_group": "deer",
            "license_year": 2026,
            "page_reference": _BASE_PAGE_REF,
            "verbatim_text": "HD 124 deer verbatim",
            "rows": [
                {
                    "license_code": "General Deer License",
                    "opportunity": "Buck Deer",
                    "apply_by": None,
                    "quota": None,
                    "quota_range": None,
                    "season_coverage": {"archery_only": True, "general": True},
                    "season_windows": {
                        "archery_only": {"window": "Sep 05-Oct 18", "weapon_type_override": "archery"},
                        "general": {"window": "Oct 24-Nov 29", "weapon_type_override": None},
                    },
                    "weapon_types": ["any_legal_weapon"],
                    "extras": None,
                    "extraction_confidence": "high",
                    "page_reference": _BASE_PAGE_REF,
                },
                {
                    "license_code": "Deer B License: 124-01",
                    "opportunity": "Antlerless Deer",
                    "apply_by": None,
                    "quota": 30,
                    "quota_range": None,
                    "season_coverage": {"general": True},
                    "season_windows": {
                        "general": {"window": "Oct 24-Nov 29", "weapon_type_override": None},
                    },
                    "weapon_types": ["any_legal_weapon"],
                    "extras": None,
                    "extraction_confidence": "high",
                    "page_reference": _BASE_PAGE_REF,
                },
            ],
        }

    def test_regulation_season_fans_out_deer_to_two_species(
        self, hd124_deer_section: dict
    ) -> None:
        links = _build_dea_regulation_season_links([hd124_deer_section])
        # 2 unique seasons × 2 target species (mule_deer + whitetail) = 4 rows
        assert len(links) == 4
        species_groups = {lk.species_group for lk in links}
        assert species_groups == {"mule_deer", "whitetail"}

    def test_regulation_season_same_season_definition_shared_across_fanout(
        self, hd124_deer_section: dict
    ) -> None:
        links = _build_dea_regulation_season_links([hd124_deer_section])
        mule_deer_links = [lk for lk in links if lk.species_group == "mule_deer"]
        whitetail_links = [lk for lk in links if lk.species_group == "whitetail"]
        # Both species reference the SAME season_definition_ids
        mule_deer_sd_ids = {lk.season_definition_id for lk in mule_deer_links}
        whitetail_sd_ids = {lk.season_definition_id for lk in whitetail_links}
        assert mule_deer_sd_ids == whitetail_sd_ids

    def test_regulation_license_fans_out_deer_to_two_species(
        self, hd124_deer_section: dict
    ) -> None:
        links = _build_dea_regulation_license_links([hd124_deer_section])
        # 2 artifact rows × 2 target species (mule_deer + whitetail) = 4 rows
        assert len(links) == 4
        species_groups = {lk.species_group for lk in links}
        assert species_groups == {"mule_deer", "whitetail"}


# ---------------------------------------------------------------------------
# TestBuildBearSeasonDefinitions
# ---------------------------------------------------------------------------


class TestBuildBearSeasonDefinitions:
    def test_bmu411_general_has_quota_threshold_closure(
        self, mock_bear_artifact: dict
    ) -> None:
        defs = _build_bear_season_definitions(mock_bear_artifact)
        bmu411_general = next(
            d for d in defs if d.id == "MT-BMU-411-bear-general-2026"
        )
        assert bmu411_general.closure_predicate is not None
        assert bmu411_general.closure_predicate.kind == "quota_threshold"
        assert bmu411_general.closure_predicate.notification_channel == "agency_phone"

    def test_bmu411_archery_only_has_quota_threshold_closure(
        self, mock_bear_artifact: dict
    ) -> None:
        defs = _build_bear_season_definitions(mock_bear_artifact)
        bmu411_archery = next(
            d for d in defs if d.id == "MT-BMU-411-bear-archery-only-2026"
        )
        assert bmu411_archery.closure_predicate is not None
        assert bmu411_archery.closure_predicate.kind == "quota_threshold"

    def test_bmu411_spring_has_no_closure(
        self, mock_bear_artifact: dict
    ) -> None:
        defs = _build_bear_season_definitions(mock_bear_artifact)
        bmu411_spring = next(
            d for d in defs if d.id == "MT-BMU-411-bear-spring-2026"
        )
        assert bmu411_spring.closure_predicate is None

    def test_bmu300_spring_has_sex_threshold_closure(
        self, mock_bear_artifact: dict
    ) -> None:
        defs = _build_bear_season_definitions(mock_bear_artifact)
        bmu300_spring = next(
            d for d in defs if d.id == "MT-BMU-300-bear-spring-2026"
        )
        assert bmu300_spring.closure_predicate is not None
        assert bmu300_spring.closure_predicate.kind == "sex_threshold"
        assert bmu300_spring.closure_predicate.notification_channel == "agency_website"
        assert bmu300_spring.closure_predicate.threshold_percent == 37.0
        assert bmu300_spring.closure_predicate.threshold_sex == "female"
        assert bmu300_spring.closure_predicate.observation_channel == "mandatory_reporting"

    def test_bmu300_general_has_no_closure(
        self, mock_bear_artifact: dict
    ) -> None:
        defs = _build_bear_season_definitions(mock_bear_artifact)
        bmu300_general = next(
            d for d in defs if d.id == "MT-BMU-300-bear-general-2026"
        )
        assert bmu300_general.closure_predicate is None

    def test_bmu300_archery_only_has_no_closure(
        self, mock_bear_artifact: dict
    ) -> None:
        defs = _build_bear_season_definitions(mock_bear_artifact)
        bmu300_archery = next(
            d for d in defs if d.id == "MT-BMU-300-bear-archery-only-2026"
        )
        assert bmu300_archery.closure_predicate is None

    def test_bmu100_no_closure_on_any_season(
        self, mock_bear_artifact: dict
    ) -> None:
        defs = _build_bear_season_definitions(mock_bear_artifact)
        bmu100_defs = [d for d in defs if d.id.startswith("MT-BMU-100-bear-")]
        assert len(bmu100_defs) == 3
        for d in bmu100_defs:
            assert d.closure_predicate is None, (
                f"BMU 100 season {d.id!r} should have no closure_predicate"
            )

    @pytest.mark.parametrize("bmu_number", [411, 420, 440, 450, 510, 520, 600, 700])
    def test_8_quota_closure_bmus_locked(
        self, mock_bear_artifact: dict, bmu_number: int
    ) -> None:
        """Lock the complete 8-BMU quota-closure set (530 excluded per S03.4)."""
        # Build a full artifact with all 8 BMUs present.
        full_rows = [
            {
                "bmu_number": bmu_number,
                "hd_region": "RX",
                "opportunity": "Either-sex",
                "general_season": "Sep 15-Nov 29",
                "archery_only_season": "Sep 05-Sep 14",
                "spring_season": "Apr 15-Jun 15",
                "hound_training_season": None,
                "hound_nr_license": None,
                "hound_nr_max": None,
                "fall_quota": {"count": None, "kind": None, "verbatim": "-"},
                "spring_quota": {"count": None, "kind": None, "verbatim": "-"},
                "page_reference": _BASE_PAGE_REF,
                "verbatim_text": f"BMU {bmu_number} verbatim",
                "extraction_confidence": "medium",
                "source_id": "mt-fwp-black-bear-2026-booklet",
                "source_publication_date": "2026-04-27",
                "applied_correction": False,
                "supersedes": None,
            }
        ]
        artifact = {
            "state": "US-MT",
            "species_group": "black_bear",
            "license_year": 2026,
            "sources": [
                {
                    "id": "mt-fwp-black-bear-2026-booklet",
                    "agency": "Montana FWP",
                    "title": "Black Bear 2026",
                    "url": "https://example.com/bear.pdf",
                    "publication_date": "2026-04-27",
                    "document_type": "annual_regulations",
                }
            ],
            "rows": full_rows,
            "closures": [
                {
                    "bmu_numbers": [411, 420, 440, 450, 510, 520, 600, 700],
                    "kind": "quota_threshold",
                    "threshold_percent": None,
                    "threshold_sex": None,
                    "notification_channel": "agency_phone",
                    "observation_channel": "mandatory_reporting",
                    "verbatim_rule": "Quota-closure prose...",
                    "page_reference": _BASE_PAGE_REF,
                    "source_id": "mt-fwp-black-bear-2026-booklet",
                    "source_publication_date": "2026-04-27",
                    "extraction_confidence": "medium",
                },
            ],
            "reporting_obligations": [],
        }
        defs = _build_bear_season_definitions(artifact)
        general = next(d for d in defs if d.id == f"MT-BMU-{bmu_number}-bear-general-2026")
        assert general.closure_predicate is not None
        assert general.closure_predicate.kind == "quota_threshold"

    def test_530_not_in_quota_closure_set(
        self, mock_bear_artifact: dict
    ) -> None:
        """BMU 530 is absent from V1 artifact (per S03.4) — assert no 530 definitions."""
        defs = _build_bear_season_definitions(mock_bear_artifact)
        bmu530_ids = [d.id for d in defs if "530" in d.id]
        assert bmu530_ids == []

    def test_archery_only_weapon_type_is_archery(
        self, mock_bear_artifact: dict
    ) -> None:
        defs = _build_bear_season_definitions(mock_bear_artifact)
        archery_defs = [d for d in defs if "archery-only" in d.id]
        assert all(d.weapon_type == "archery" for d in archery_defs)

    def test_general_spring_weapon_type_is_none(
        self, mock_bear_artifact: dict
    ) -> None:
        defs = _build_bear_season_definitions(mock_bear_artifact)
        non_archery = [d for d in defs if "archery" not in d.id]
        assert all(d.weapon_type is None for d in non_archery)

    def test_sex_threshold_closure_locks_4_bmus(self, mock_bear_artifact: dict) -> None:
        """Lock the 4-BMU female-sub-quota set: 300, 301, 319, 580.
        The per-BMU closure attachment logic is exercised by BMU 300; this
        test locks the data contract that all 4 BMUs are in the closure set.
        """
        sex_closure = next(
            c for c in mock_bear_artifact["closures"]
            if c["kind"] == "sex_threshold"
        )
        assert set(sex_closure["bmu_numbers"]) == {300, 301, 319, 580}


# ---------------------------------------------------------------------------
# TestBuildBearLicenseTags
# ---------------------------------------------------------------------------


class TestBuildBearLinkRows:
    def test_license_season_links_count(self, mock_bear_artifact: dict) -> None:
        # 3 BMUs × 3 non-null season fields each = 9 links
        links = _build_bear_license_season_links(mock_bear_artifact)
        assert len(links) == 9

    def test_license_season_links_structure(self, mock_bear_artifact: dict) -> None:
        links = _build_bear_license_season_links(mock_bear_artifact)
        bmu411_links = [lk for lk in links if lk.license_tag_id == "MT-BMU-411-bear-2026"]
        # BMU 411 has general + archery_only + spring (3 non-null)
        assert len(bmu411_links) == 3
        bmu411_sd_ids = {lk.season_definition_id for lk in bmu411_links}
        assert bmu411_sd_ids == {
            "MT-BMU-411-bear-general-2026",
            "MT-BMU-411-bear-archery-only-2026",
            "MT-BMU-411-bear-spring-2026",
        }

    def test_regulation_season_links_count(self, mock_bear_artifact: dict) -> None:
        # 3 BMUs × 3 non-null season fields each = 9 links
        links = _build_bear_regulation_season_links(mock_bear_artifact)
        assert len(links) == 9

    def test_regulation_season_links_species_group(self, mock_bear_artifact: dict) -> None:
        links = _build_bear_regulation_season_links(mock_bear_artifact)
        assert all(lk.species_group == "bear" for lk in links)

    def test_regulation_season_links_jurisdiction_code(self, mock_bear_artifact: dict) -> None:
        links = _build_bear_regulation_season_links(mock_bear_artifact)
        bmu411_links = [lk for lk in links if "411" in lk.jurisdiction_code]
        assert all(lk.jurisdiction_code == "MT-HD-bear-411" for lk in bmu411_links)

    def test_regulation_license_links_count(self, mock_bear_artifact: dict) -> None:
        # 3 BMUs → 3 regulation_license rows (one per BMU)
        links = _build_bear_regulation_license_links(mock_bear_artifact)
        assert len(links) == 3

    def test_regulation_license_links_structure(self, mock_bear_artifact: dict) -> None:
        links = _build_bear_regulation_license_links(mock_bear_artifact)
        bmu100_link = next(lk for lk in links if "100" in lk.jurisdiction_code)
        assert bmu100_link.jurisdiction_code == "MT-HD-bear-100"
        assert bmu100_link.species_group == "bear"
        assert bmu100_link.license_tag_id == "MT-BMU-100-bear-2026"


class TestBuildBearLicenseTags:
    def test_one_license_tag_per_bmu(self, mock_bear_artifact: dict) -> None:
        tags = _build_bear_license_tags(mock_bear_artifact)
        # 3 BMUs in the fixture
        assert len(tags) == 3

    def test_species_is_bear_not_black_bear(self, mock_bear_artifact: dict) -> None:
        tags = _build_bear_license_tags(mock_bear_artifact)
        assert all(t.species == "bear" for t in tags)

    def test_quota_from_fall_quota_count(self, mock_bear_artifact: dict) -> None:
        tags = _build_bear_license_tags(mock_bear_artifact)
        bmu411_tag = next(t for t in tags if t.id == "MT-BMU-411-bear-2026")
        assert bmu411_tag.quota == 4  # fall_quota.count for BMU 411

    def test_quota_none_when_absent(self, mock_bear_artifact: dict) -> None:
        tags = _build_bear_license_tags(mock_bear_artifact)
        bmu100_tag = next(t for t in tags if t.id == "MT-BMU-100-bear-2026")
        # BMU 100 has fall_quota.count=None
        assert bmu100_tag.quota is None

    def test_quota_range_is_none(self, mock_bear_artifact: dict) -> None:
        tags = _build_bear_license_tags(mock_bear_artifact)
        assert all(t.quota_range is None for t in tags)

    def test_weapon_types_is_any_legal_weapon(self, mock_bear_artifact: dict) -> None:
        tags = _build_bear_license_tags(mock_bear_artifact)
        assert all(t.weapon_types == ["any_legal_weapon"] for t in tags)

    def test_kind_is_general(self, mock_bear_artifact: dict) -> None:
        tags = _build_bear_license_tags(mock_bear_artifact)
        assert all(t.kind == "general" for t in tags)

    def test_draw_spec_key_is_none(self, mock_bear_artifact: dict) -> None:
        tags = _build_bear_license_tags(mock_bear_artifact)
        assert all(t.draw_spec_key is None for t in tags)

    def test_reserved_pools_is_empty(self, mock_bear_artifact: dict) -> None:
        tags = _build_bear_license_tags(mock_bear_artifact)
        assert all(t.reserved_pools == [] for t in tags)


# ---------------------------------------------------------------------------
# TestStatewideOverlay
# ---------------------------------------------------------------------------


class TestStatewideOverlay:
    @pytest.fixture
    def statewide_section(self) -> dict:
        return {
            "hd_number": "STATEWIDE",
            "hd_name": "Statewide",
            "species_group": "antelope",
            "license_year": 2026,
            "page_reference": _BASE_PAGE_REF,
            "verbatim_text": "STATEWIDE antelope 900-20 verbatim text",
            "rows": [
                {
                    "license_code": "Antelope License: 900-20",
                    "opportunity": "Either-sex Statewide",
                    "apply_by": None,
                    "quota": 5600,
                    "quota_range": "1-7,500",
                    "season_coverage": {
                        "archery_only": True,
                        "general": True,
                    },
                    "season_windows": {
                        "archery_only": {"window": "Aug. 15-Nov. 08", "weapon_type_override": "archery"},
                        "general": {"window": "Oct 24-Nov 08", "weapon_type_override": None},
                    },
                    "weapon_types": ["archery"],
                    "extras": None,
                    "extraction_confidence": "high",
                    "page_reference": _BASE_PAGE_REF,
                },
            ],
        }

    @pytest.fixture
    def statewide_citation(self) -> SourceCitation:
        return SourceCitation(
            id="mt-fwp-dea-2026-booklet",
            agency="Montana FWP",
            title="DEA 2026",
            url="https://example.com/dea.pdf",
            publication_date="2026-04-27",
            document_type="annual_regulations",
        )

    def test_license_tag_kind_is_statewide(
        self, statewide_section: dict, statewide_citation: SourceCitation
    ) -> None:
        tags = _build_dea_license_tags([statewide_section], statewide_citation)
        assert len(tags) == 1
        assert tags[0].kind == "statewide"

    def test_license_tag_weapon_types(
        self, statewide_section: dict, statewide_citation: SourceCitation
    ) -> None:
        tags = _build_dea_license_tags([statewide_section], statewide_citation)
        assert tags[0].weapon_types == ["archery"]

    def test_license_tag_quota(
        self, statewide_section: dict, statewide_citation: SourceCitation
    ) -> None:
        tags = _build_dea_license_tags([statewide_section], statewide_citation)
        assert tags[0].quota == 5600

    def test_license_tag_quota_range(
        self, statewide_section: dict, statewide_citation: SourceCitation
    ) -> None:
        tags = _build_dea_license_tags([statewide_section], statewide_citation)
        assert tags[0].quota_range == (1, 7500)

    def test_season_definitions_produced(
        self, statewide_section: dict, statewide_citation: SourceCitation
    ) -> None:
        defs = _build_dea_season_definitions([statewide_section], statewide_citation)
        assert len(defs) == 2
        ids = {d.id for d in defs}
        assert "MT-STATEWIDE-antelope-archery-only-2026" in ids
        assert "MT-STATEWIDE-antelope-general-2026" in ids

    def test_license_season_links(
        self, statewide_section: dict
    ) -> None:
        links = _build_dea_license_season_links([statewide_section])
        # 1 row with 2 season_windows → 2 license_season links
        assert len(links) == 2
        tag_id = "MT-STATEWIDE-antelope-antelope-900-20-2026"
        assert all(lk.license_tag_id == tag_id for lk in links)

    def test_regulation_season_links(
        self, statewide_section: dict
    ) -> None:
        links = _build_dea_regulation_season_links([statewide_section])
        # 1 target species (pronghorn) × 2 unique seasons = 2 rows
        assert len(links) == 2
        assert all(lk.jurisdiction_code == "MT-STATEWIDE-antelope" for lk in links)
        assert all(lk.species_group == "pronghorn" for lk in links)

    def test_regulation_license_links(
        self, statewide_section: dict
    ) -> None:
        links = _build_dea_regulation_license_links([statewide_section])
        # 1 artifact row × 1 target species = 1 link
        assert len(links) == 1
        assert links[0].jurisdiction_code == "MT-STATEWIDE-antelope"
        assert links[0].species_group == "pronghorn"


# ---------------------------------------------------------------------------
# TestCountGuards
# ---------------------------------------------------------------------------


class TestCountGuards:
    # season_definition guard: expected=978, lower=684, upper=1271

    def test_season_definition_in_band_passes(self) -> None:
        _assert_season_definition_count_within_guard(978)
        _assert_season_definition_count_within_guard(684)
        _assert_season_definition_count_within_guard(1271)

    def test_season_definition_below_band_raises(self) -> None:
        with pytest.raises(RuntimeError, match="season_definition"):
            _assert_season_definition_count_within_guard(683)

    def test_season_definition_above_band_raises(self) -> None:
        with pytest.raises(RuntimeError, match="season_definition"):
            _assert_season_definition_count_within_guard(1272)

    def test_season_definition_zero_raises(self) -> None:
        with pytest.raises(RuntimeError, match="season_definition"):
            _assert_season_definition_count_within_guard(0)

    def test_season_definition_small_value_raises(self) -> None:
        with pytest.raises(RuntimeError, match="season_definition"):
            _assert_season_definition_count_within_guard(50)

    # license_tag guard: expected=1225, lower=857, upper=1592

    def test_license_tag_in_band_passes(self) -> None:
        _assert_license_tag_count_within_guard(1225)
        _assert_license_tag_count_within_guard(857)
        _assert_license_tag_count_within_guard(1592)

    def test_license_tag_below_band_raises(self) -> None:
        with pytest.raises(RuntimeError, match="license_tag"):
            _assert_license_tag_count_within_guard(856)

    def test_license_tag_above_band_raises(self) -> None:
        with pytest.raises(RuntimeError, match="license_tag"):
            _assert_license_tag_count_within_guard(1593)

    # license_season guard: expected=3040, lower=2128, upper=3952

    def test_license_season_in_band_passes(self) -> None:
        _assert_license_season_count_within_guard(3040)
        _assert_license_season_count_within_guard(2128)
        _assert_license_season_count_within_guard(3952)

    def test_license_season_below_band_raises(self) -> None:
        with pytest.raises(RuntimeError, match="license_season"):
            _assert_license_season_count_within_guard(2127)

    def test_license_season_above_band_raises(self) -> None:
        with pytest.raises(RuntimeError, match="license_season"):
            _assert_license_season_count_within_guard(3953)

    # regulation_season guard: expected=1385, lower=969, upper=1800

    def test_regulation_season_in_band_passes(self) -> None:
        _assert_regulation_season_count_within_guard(1385)
        _assert_regulation_season_count_within_guard(969)
        _assert_regulation_season_count_within_guard(1800)

    def test_regulation_season_below_band_raises(self) -> None:
        with pytest.raises(RuntimeError, match="regulation_season"):
            _assert_regulation_season_count_within_guard(968)

    def test_regulation_season_above_band_raises(self) -> None:
        with pytest.raises(RuntimeError, match="regulation_season"):
            _assert_regulation_season_count_within_guard(1801)

    # regulation_license guard: expected=1914, lower=1339, upper=2488

    def test_regulation_license_in_band_passes(self) -> None:
        _assert_regulation_license_count_within_guard(1914)
        _assert_regulation_license_count_within_guard(1339)
        _assert_regulation_license_count_within_guard(2488)

    def test_regulation_license_below_band_raises(self) -> None:
        with pytest.raises(RuntimeError, match="regulation_license"):
            _assert_regulation_license_count_within_guard(1338)

    def test_regulation_license_above_band_raises(self) -> None:
        with pytest.raises(RuntimeError, match="regulation_license"):
            _assert_regulation_license_count_within_guard(2489)


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------


class TestMain:
    def test_dry_run_exits_zero(self, caplog: pytest.LogCaptureFixture) -> None:
        """Dry-run must build all entities, pass guards, and return 0."""
        with caplog.at_level(logging.INFO):
            exit_code = main(["--dry-run"])
        assert exit_code == 0

    def test_dry_run_logs_five_count_totals(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """All five entity counts appear in the INFO log output."""
        with caplog.at_level(logging.INFO):
            main(["--dry-run"])
        log_text = caplog.text
        # Verify that the summary build log message fires (counts logged).
        # The format is "built: %d season_definition, %d license_tag, ..."
        assert "season_definition" in log_text
        assert "license_tag" in log_text
        assert "license_season" in log_text
        assert "regulation_season" in log_text
        assert "regulation_license" in log_text

    def test_dry_run_does_not_call_db_connect(self) -> None:
        """Dry-run must NOT touch the database."""
        from unittest.mock import patch
        import states.montana.load_seasons_and_licenses as lsal

        with patch.object(lsal.db, "connect") as mock_connect:
            exit_code = main(["--dry-run"])
        assert exit_code == 0
        mock_connect.assert_not_called()

    def test_dry_run_count_guard_passes_on_real_artifacts(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If the real artifacts are present, all five count guards must pass.
        This implicitly asserts artifact baseline integrity."""
        with caplog.at_level(logging.WARNING):
            # Raises RuntimeError if any guard fails — test fails if so.
            exit_code = main(["--dry-run"])
        assert exit_code == 0


# ---------------------------------------------------------------------------
# TestOtcCrossRowDiscrimination
# ---------------------------------------------------------------------------


def _make_b_license_section(
    hd_number: str,
    species_group: str,
    license_code: str,
    apply_by_values: list[str | None],
) -> dict:
    """Build a minimal synthetic DEA section with one or more B License rows.

    Each entry in apply_by_values produces one row with the same identity
    (species_group, hd_number, license_code) but the given apply_by value.
    """
    rows = [
        {
            "license_code": license_code,
            "opportunity": "Test Opportunity",
            "apply_by": apply_by,
            "quota": None,
            "quota_range": None,
            "season_coverage": {"general": True},
            "season_windows": {
                "general": {"window": "Oct 24-Nov 29", "weapon_type_override": None},
            },
            "weapon_types": ["any_legal_weapon"],
            "extras": None,
            "extraction_confidence": "high",
            "page_reference": _BASE_PAGE_REF,
        }
        for apply_by in apply_by_values
    ]
    return {
        "hd_number": hd_number,
        "hd_name": f"HD {hd_number}",
        "species_group": species_group,
        "license_year": 2026,
        "page_reference": _BASE_PAGE_REF,
        "verbatim_text": f"HD {hd_number} {species_group} verbatim text",
        "rows": rows,
    }


class TestOtcCrossRowDiscrimination:
    """Locks the cross-row OTC-wins discipline in _DEA_LICENSE_KIND_HEURISTIC.

    A B License identity (species, hd, license_code) classifies as 'over_the_counter'
    if ANY artifact row for that identity has 'OTC' in its apply_by; else 'limited_draw'.
    """

    def test_single_b_license_drawing_classifies_limited_draw(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        section = _make_b_license_section(
            hd_number="262",
            species_group="elk",
            license_code="Elk B License: 262-50",
            apply_by_values=["Jun 1"],
        )
        tags = _build_dea_license_tags([section], mock_dea_citation)
        assert len(tags) == 1
        assert tags[0].kind == "limited_draw"

    def test_single_b_license_otc_classifies_over_the_counter(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        section = _make_b_license_section(
            hd_number="170",
            species_group="deer",
            license_code="Deer B License: 170-00",
            apply_by_values=["OTC:\nJun 15"],
        )
        tags = _build_dea_license_tags([section], mock_dea_citation)
        assert len(tags) == 1
        assert tags[0].kind == "over_the_counter"

    def test_duplicate_identity_otc_then_null_otc_wins(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        # Two rows with the SAME identity: row 1 has OTC apply_by, row 2 has None.
        # OTC-wins: BOTH rows' tags must be over_the_counter.
        section = _make_b_license_section(
            hd_number="213",
            species_group="deer",
            license_code="Deer B License: 213-02",
            apply_by_values=["OTC:\nJun 15", None],
        )
        tags = _build_dea_license_tags([section], mock_dea_citation)
        assert len(tags) == 2
        assert all(t.kind == "over_the_counter" for t in tags), (
            f"Expected both tags to be over_the_counter; got {[t.kind for t in tags]}"
        )

    def test_duplicate_identity_drawing_then_null_stays_limited_draw(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        # Two rows with the SAME identity: row 1 has a drawing deadline, row 2 has None.
        # No OTC in any apply_by → BOTH rows' tags must be limited_draw.
        section = _make_b_license_section(
            hd_number="300",
            species_group="elk",
            license_code="Elk B License: 300-00",
            apply_by_values=["Jun 1", None],
        )
        tags = _build_dea_license_tags([section], mock_dea_citation)
        assert len(tags) == 2
        assert all(t.kind == "limited_draw" for t in tags), (
            f"Expected both tags to be limited_draw; got {[t.kind for t in tags]}"
        )

    def test_otc_in_one_section_does_not_leak_to_another_hd(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        # HD A has OTC apply_by; HD B has a drawing deadline apply_by.
        # Both share the same license_code suffix but differ in hd_number.
        # Identity tuple is (species, hd, license_code) — hd is part of the key.
        section_a = _make_b_license_section(
            hd_number="410",
            species_group="elk",
            license_code="Elk B License: 410-00",
            apply_by_values=["OTC:\nJun 15"],
        )
        section_b = _make_b_license_section(
            hd_number="411",
            species_group="elk",
            license_code="Elk B License: 411-00",
            apply_by_values=["Jun 1"],
        )
        tags = _build_dea_license_tags([section_a, section_b], mock_dea_citation)
        assert len(tags) == 2
        tag_a = next(t for t in tags if t.license_code == "Elk B License: 410-00")
        tag_b = next(t for t in tags if t.license_code == "Elk B License: 411-00")
        assert tag_a.kind == "over_the_counter", (
            f"HD 410 tag should be over_the_counter; got {tag_a.kind!r}"
        )
        assert tag_b.kind == "limited_draw", (
            f"HD 411 tag should be limited_draw; got {tag_b.kind!r}"
        )

    def test_duplicate_identity_null_then_otc_still_otc_wins(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        """OTC-wins is cross-row regardless of artifact row order.

        The current implementation pre-computes _otc_identities by scanning all
        rows before classifying any row. This test locks against a refactor
        that moves the OTC check inline (which would make classification depend
        on row order).

        Reversed fixture from test_duplicate_identity_otc_then_null_otc_wins:
        Row 1 is null (no OTC signal); Row 2 has OTC apply_by. Both rows MUST
        classify as over_the_counter — the OTC signal from the LATER row must
        demote the EARLIER row.
        """
        section = _make_b_license_section(
            hd_number="999",
            species_group="elk",
            license_code="Elk B License: 999-99",
            apply_by_values=[None, "OTC:\nJun 15"],
        )
        tags = _build_dea_license_tags([section], mock_dea_citation)
        assert len(tags) == 2
        for tag in tags:
            assert tag.kind == "over_the_counter", (
                f"row-order regression: expected 'over_the_counter' for both rows "
                f"of identity ('elk', '999', 'Elk B License: 999-99'); "
                f"got {tag.kind!r} for tag.id={tag.id!r}"
            )

    def test_non_string_apply_by_raises_runtimeerror(self) -> None:
        """Synthetic row with apply_by=42 (int) → RuntimeError naming apply_by and schema drift."""
        bad_row = {
            "license_code": "Elk B License: 999-00",
            "apply_by": 42,  # int, not str|None — schema drift
            "quota": None,
            "quota_range": None,
            "season_coverage": {"general": True},
            "season_windows": {
                "general": {"window": "Oct 24-Nov 29", "weapon_type_override": None},
            },
            "weapon_types": ["any_legal_weapon"],
            "extras": None,
            "extraction_confidence": "high",
            "page_reference": _BASE_PAGE_REF,
        }
        with pytest.raises(RuntimeError, match="apply_by") as exc_info:
            _row_has_otc(bad_row)
        assert "schema drift" in str(exc_info.value), (
            f"RuntimeError message must mention 'schema drift'; got: {exc_info.value!r}"
        )

    def test_absent_apply_by_key_raises_runtimeerror(self) -> None:
        """Synthetic row WITHOUT an apply_by key entirely → RuntimeError.

        Distinguishes "key removed from artifact schema" (drift) from
        "key present with None value" (legitimate). The bare `.get()`
        idiom collapses both cases to None silently; an absent-key check
        surfaces schema drift loudly.
        """
        bad_row = {
            "license_code": "Elk B License: 999-00",
            # NOTE: no "apply_by" key at all (schema-drift scenario)
            "quota": None,
            "quota_range": None,
            "season_coverage": {"general": True},
            "season_windows": {
                "general": {"window": "Oct 24-Nov 29", "weapon_type_override": None},
            },
            "weapon_types": ["any_legal_weapon"],
            "extras": None,
            "extraction_confidence": "high",
            "page_reference": _BASE_PAGE_REF,
        }
        with pytest.raises(RuntimeError, match="apply_by") as exc_info:
            _row_has_otc(bad_row)
        assert "missing" in str(exc_info.value), (
            f"RuntimeError message must mention 'missing'; got: {exc_info.value!r}"
        )
        assert "schema drift" in str(exc_info.value), (
            f"RuntimeError message must mention 'schema drift'; got: {exc_info.value!r}"
        )


# ---------------------------------------------------------------------------
# TestRealArtifactKindCountsAfterOtcDiscrimination
# ---------------------------------------------------------------------------


class TestRealArtifactKindCountsAfterOtcDiscrimination:
    """Real-artifact regression locks the PM-confirmed baseline.

    Post-amended-heuristic post-dedup counts MUST match (drift signal):
    - 390 limited_draw
    - 160 over_the_counter
    - 239 general
    - 1 statewide
    Total: 790 DEA license_tag identities.
    """

    def test_real_artifact_kind_distribution(
        self, mock_dea_citation: SourceCitation
    ) -> None:
        import json
        import pathlib
        from collections import Counter

        artifact_path = (
            pathlib.Path(__file__).parent.parent
            / "states" / "montana" / "extracted" / "dea-2026.json"
        )
        with artifact_path.open() as f:
            dea_artifact = json.load(f)

        tags = _build_dea_license_tags(dea_artifact, mock_dea_citation)

        # Dedup by id (mirrors DB upsert behavior: last-write-wins on structural fields;
        # only kind is needed here so any collision produces the same kind value).
        deduped: dict[str, str] = {t.id: t.kind for t in tags}
        kind_counts = Counter(deduped.values())

        assert kind_counts["limited_draw"] == 390, (
            f"Expected 390 limited_draw; got {kind_counts['limited_draw']}"
        )
        assert kind_counts["over_the_counter"] == 160, (
            f"Expected 160 over_the_counter; got {kind_counts['over_the_counter']}"
        )
        assert kind_counts["general"] == 239, (
            f"Expected 239 general; got {kind_counts['general']}"
        )
        assert kind_counts["statewide"] == 1, (
            f"Expected 1 statewide; got {kind_counts['statewide']}"
        )
        assert sum(kind_counts.values()) == 790, (
            f"Expected 790 total deduped tags; got {sum(kind_counts.values())}"
        )
