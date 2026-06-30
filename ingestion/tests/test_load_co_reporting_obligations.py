"""Unit tests for states.colorado.load_reporting_obligations (S06.9).

Covers:
- TestDeriveExpectedIdSuffix     — pure slug-encoding function
- TestReportingRowSpec           — dispatch dict shape + field values
- TestDispatchDictDriftGuard     — assert_dispatch_dict_drift_free behaviour
- TestBuildReportingObligations  — happy path + fail-loud cases
- TestCountGuard                 — exact-match (1, 1) band
- TestDocumentTypeGuard          — allowed / rejected document_type values
- TestMain                       — --dry-run and -v short-circuit paths
- TestNoLibImports               — AST-walk: no sibling-state imports
- TestNoLayoutTrueRegression     — AST-walk: no layout=True in loader

All tests are hermetic — no live DB, no live PDF, no network.
"""

from __future__ import annotations

import ast
import importlib.util
import json
from copy import deepcopy
from pathlib import Path

import pytest

from ingestion.lib.drift_guard import assert_dispatch_dict_drift_free
from ingestion.lib.schema import SourceCitation
from states.colorado import load_reporting_obligations as mod


# ---------------------------------------------------------------------------
# Helper: loader source path (mirrors test_load_co_regulation_records.py)
# ---------------------------------------------------------------------------


def _loader_source_path() -> Path:
    spec = importlib.util.find_spec("states.colorado.load_reporting_obligations")
    assert spec is not None and spec.origin is not None
    return Path(spec.origin)


# ---------------------------------------------------------------------------
# Helper: build a minimal valid reporting_obligation artifact entry
# ---------------------------------------------------------------------------

_VALID_PAGE_REFERENCE: dict = {  # type: ignore[type-arg]
    "pdf_filename": "co-cpw-big-game-2026-brochure-2026-03-04.pdf",
    "page_num_1based": 73,
    "bbox": None,
    "extracted_at": "2026-06-04T00:00:00+00:00",
}


def _make_ro_entry(
    region_scope: str = "STATEWIDE",
    kind_hint: str = "mandatory_inspection",
    source_id: str = "co-cpw-big-game-2026-brochure",
    verbatim_rule: str = "Mandatory Bear Inspections & Seals",
    page_reference: dict | None = None,  # type: ignore[type-arg]
) -> dict:  # type: ignore[type-arg]
    """Minimal synthetic reporting_obligation flat-list entry."""
    return {
        "record_type": "reporting_obligation",
        "region_scope": region_scope,
        "kind_hint": kind_hint,
        "source_id": source_id,
        "page_reference": page_reference if page_reference is not None else deepcopy(_VALID_PAGE_REFERENCE),
        "verbatim_rule": verbatim_rule,
    }


def _make_section_entry(gmu_code: str = "082") -> dict:  # type: ignore[type-arg]
    return {
        "record_type": "section",
        "gmu_code": gmu_code,
        "species_group": "black_bear",
        "method_group": "rifle",
        "page_reference": deepcopy(_VALID_PAGE_REFERENCE),
        "verbatim_text": "B-E-082-R1-R",
        "rows": [{"extraction_confidence": "high"}],
    }


def _make_statewide_rule_entry(rule_hint: str = "season_dates_summary") -> dict:  # type: ignore[type-arg]
    return {
        "record_type": "statewide_rule",
        "rule_hint": rule_hint,
        "source_id": "co-cpw-big-game-2026-brochure",
    }


# ---------------------------------------------------------------------------
# TestDeriveExpectedIdSuffix
# ---------------------------------------------------------------------------


class TestDeriveExpectedIdSuffix:
    """Pure slug-encoding function tests."""

    def test_mandatory_check_5day_statewide(self) -> None:
        """kind=mandatory_check, 120 hrs, STATEWIDE → 'mandatory-check-5day-statewide'."""
        result = mod._derive_expected_id_suffix("mandatory_check", 120, "STATEWIDE")
        assert result == "mandatory-check-5day-statewide"

    def test_48hr_branch(self) -> None:
        """deadline_hours <= 48 → hours form, e.g. 48 → '48hr'."""
        result = mod._derive_expected_id_suffix("harvest_report", 48, "STATEWIDE")
        assert result == "harvest-report-48hr-statewide"

    def test_24hr_boundary(self) -> None:
        """24 hours (exactly 1 day, but <= 48) → '24hr' not '1day'."""
        result = mod._derive_expected_id_suffix("harvest_report", 24, "STATEWIDE")
        assert result == "harvest-report-24hr-statewide"

    def test_multiple_of_24_above_48(self) -> None:
        """72 hours (> 48, multiple of 24) → '3day'."""
        result = mod._derive_expected_id_suffix("tooth_submission", 72, "STATEWIDE")
        assert result == "tooth-submission-3day-statewide"

    def test_240_hours_is_10day(self) -> None:
        """240 hours → '10day'."""
        result = mod._derive_expected_id_suffix("mandatory_check", 240, "STATEWIDE")
        assert result == "mandatory-check-10day-statewide"

    def test_unknown_region_scope_raises(self) -> None:
        """region_scope not in _REGION_SCOPE_SLUG → RuntimeError."""
        with pytest.raises(RuntimeError, match="R9"):
            mod._derive_expected_id_suffix("mandatory_check", 120, "R9")

    def test_non_representable_deadline_hours_raises(self) -> None:
        """deadline_hours=50: > 48 but not a multiple of 24 → RuntimeError."""
        with pytest.raises(RuntimeError, match="50"):
            mod._derive_expected_id_suffix("mandatory_check", 50, "STATEWIDE")

    def test_non_representable_hours_97(self) -> None:
        """97 hours is > 48 and not a multiple of 24 → RuntimeError."""
        with pytest.raises(RuntimeError, match="97"):
            mod._derive_expected_id_suffix("harvest_report", 97, "STATEWIDE")

    def test_kind_underscore_to_hyphen(self) -> None:
        """Underscores in kind are converted to hyphens in the slug."""
        result = mod._derive_expected_id_suffix("hide_skull_presentation", 120, "STATEWIDE")
        assert "_" not in result
        assert "hide-skull-presentation" in result


# ---------------------------------------------------------------------------
# TestReportingRowSpec
# ---------------------------------------------------------------------------


class TestReportingRowSpec:
    """Dispatch dict shape + locked field values."""

    def test_has_exactly_one_key(self) -> None:
        """_REPORTING_ROW_SPEC has exactly one entry."""
        assert len(mod._REPORTING_ROW_SPEC) == 1

    def test_key_is_statewide_mandatory_inspection(self) -> None:
        """The one key is ('STATEWIDE', 'mandatory_inspection')."""
        keys = list(mod._REPORTING_ROW_SPEC.keys())
        assert keys[0] == ("STATEWIDE", "mandatory_inspection")

    def test_entry_kind_is_valid(self) -> None:
        """entry['kind'] is in the 6-value ReportingObligation.kind Literal set."""
        valid_kinds = {
            "harvest_report",
            "mandatory_check",
            "tooth_submission",
            "hide_skull_presentation",
            "cwd_sample",
            "other",
        }
        entry = mod._REPORTING_ROW_SPEC[("STATEWIDE", "mandatory_inspection")]
        assert entry["kind"] in valid_kinds

    def test_entry_kind_is_mandatory_check(self) -> None:
        """entry['kind'] == 'mandatory_check'."""
        entry = mod._REPORTING_ROW_SPEC[("STATEWIDE", "mandatory_inspection")]
        assert entry["kind"] == "mandatory_check"

    def test_id_suffix_matches_derivation(self) -> None:
        """entry['id_suffix'] equals _derive_expected_id_suffix(kind, deadline_hours, 'STATEWIDE')."""
        entry = mod._REPORTING_ROW_SPEC[("STATEWIDE", "mandatory_inspection")]
        derived = mod._derive_expected_id_suffix(
            entry["kind"], entry["deadline_hours"], "STATEWIDE"
        )
        assert entry["id_suffix"] == derived

    def test_applies_to_regions_is_none(self) -> None:
        """applies_to_regions is None (statewide)."""
        entry = mod._REPORTING_ROW_SPEC[("STATEWIDE", "mandatory_inspection")]
        assert entry["applies_to_regions"] is None

    def test_what_to_present(self) -> None:
        """what_to_present == ['bear head', 'hide']."""
        entry = mod._REPORTING_ROW_SPEC[("STATEWIDE", "mandatory_inspection")]
        assert entry["what_to_present"] == ["bear head", "hide"]

    def test_deadline_hours(self) -> None:
        """deadline_hours == 120."""
        entry = mod._REPORTING_ROW_SPEC[("STATEWIDE", "mandatory_inspection")]
        assert entry["deadline_hours"] == 120

    def test_submission_method(self) -> None:
        """submission_method == 'agency_office'."""
        entry = mod._REPORTING_ROW_SPEC[("STATEWIDE", "mandatory_inspection")]
        assert entry["submission_method"] == "agency_office"


# ---------------------------------------------------------------------------
# TestDispatchDictDriftGuard
# ---------------------------------------------------------------------------


class TestDispatchDictDriftGuard:
    """assert_dispatch_dict_drift_free behaviour with _REPORTING_ROW_SPEC."""

    def test_import_does_not_raise(self) -> None:
        """Importing mod does not raise — the real dict is drift-free."""
        # If the module-level assert_dispatch_dict_drift_free call had failed,
        # the import itself would have raised. Reaching this line proves it passed.
        assert mod is not None

    def test_mutated_id_suffix_raises(self) -> None:
        """A copy with a wrong id_suffix raises RuntimeError mentioning _REPORTING_ROW_SPEC."""
        mutated = deepcopy(dict(mod._REPORTING_ROW_SPEC))
        mutated[("STATEWIDE", "mandatory_inspection")]["id_suffix"] = "wrong-value"

        with pytest.raises(RuntimeError, match="_REPORTING_ROW_SPEC"):
            assert_dispatch_dict_drift_free(
                mutated,
                lambda key, entry: mod._derive_expected_id_suffix(
                    entry["kind"], entry["deadline_hours"], key[0],
                ),
                helper_name="_REPORTING_ROW_SPEC",
                id_field="id_suffix",
            )

    def test_missing_id_suffix_field_raises(self) -> None:
        """A copy whose entry is missing id_suffix raises RuntimeError."""
        mutated = {
            ("STATEWIDE", "mandatory_inspection"): {
                "kind": "mandatory_check",
                "deadline": "5 working days",
                "deadline_hours": 120,
                # id_suffix intentionally omitted
                "submission_method": "agency_office",
                "submission_url": None,
                "submission_phone": None,
                "applies_to_regions": None,
                "what_to_present": ["bear head", "hide"],
            }
        }

        with pytest.raises(RuntimeError):
            assert_dispatch_dict_drift_free(
                mutated,
                lambda key, entry: mod._derive_expected_id_suffix(
                    entry["kind"], entry["deadline_hours"], key[0],
                ),
                helper_name="_REPORTING_ROW_SPEC",
                id_field="id_suffix",
            )


# ---------------------------------------------------------------------------
# TestBuildReportingObligations
# ---------------------------------------------------------------------------


class TestBuildReportingObligations:
    """Happy path + fail-loud cases for _build_reporting_obligations."""

    # --- Happy path against the committed artifact ---

    def test_happy_path_count(self) -> None:
        """Real artifact → exactly 1 obligation."""
        art = json.loads(mod._BEAR_ARTIFACT_PATH.read_text(encoding="utf-8"))
        obs = mod._build_reporting_obligations(art)
        assert len(obs) == 1

    def test_happy_path_id(self) -> None:
        """Obligation id == 'co-bear-mandatory-check-5day-statewide'."""
        art = json.loads(mod._BEAR_ARTIFACT_PATH.read_text(encoding="utf-8"))
        obs = mod._build_reporting_obligations(art)
        assert obs[0].id == "co-bear-mandatory-check-5day-statewide"

    def test_happy_path_kind(self) -> None:
        """obligation.kind == 'mandatory_check'."""
        art = json.loads(mod._BEAR_ARTIFACT_PATH.read_text(encoding="utf-8"))
        obs = mod._build_reporting_obligations(art)
        assert obs[0].kind == "mandatory_check"

    def test_happy_path_deadline(self) -> None:
        """obligation.deadline == '5 working days'."""
        art = json.loads(mod._BEAR_ARTIFACT_PATH.read_text(encoding="utf-8"))
        obs = mod._build_reporting_obligations(art)
        assert obs[0].deadline == "5 working days"

    def test_happy_path_deadline_hours(self) -> None:
        """obligation.deadline_hours == 120."""
        art = json.loads(mod._BEAR_ARTIFACT_PATH.read_text(encoding="utf-8"))
        obs = mod._build_reporting_obligations(art)
        assert obs[0].deadline_hours == 120

    def test_happy_path_submission_method(self) -> None:
        """obligation.submission_method == 'agency_office'."""
        art = json.loads(mod._BEAR_ARTIFACT_PATH.read_text(encoding="utf-8"))
        obs = mod._build_reporting_obligations(art)
        assert obs[0].submission_method == "agency_office"

    def test_happy_path_applies_to_regions(self) -> None:
        """obligation.applies_to_regions is None (statewide)."""
        art = json.loads(mod._BEAR_ARTIFACT_PATH.read_text(encoding="utf-8"))
        obs = mod._build_reporting_obligations(art)
        assert obs[0].applies_to_regions is None

    def test_happy_path_what_to_present(self) -> None:
        """obligation.what_to_present == ['bear head', 'hide']."""
        art = json.loads(mod._BEAR_ARTIFACT_PATH.read_text(encoding="utf-8"))
        obs = mod._build_reporting_obligations(art)
        assert obs[0].what_to_present == ["bear head", "hide"]

    def test_happy_path_verbatim_rule_non_empty(self) -> None:
        """obligation.verbatim_rule is a non-empty string."""
        art = json.loads(mod._BEAR_ARTIFACT_PATH.read_text(encoding="utf-8"))
        obs = mod._build_reporting_obligations(art)
        assert isinstance(obs[0].verbatim_rule, str)
        assert len(obs[0].verbatim_rule) > 0

    def test_happy_path_verbatim_rule_full_prose(self) -> None:
        """obligation.verbatim_rule contains the full p.73 rule prose (S06.9.1 recovery).

        Verifies that the S06.9.1 extract_black_bear.py re-anchor fix succeeded:
        the committed artifact's verbatim_rule is no longer the heading-only string
        but the complete CPW mandatory-inspection rule from brochure p.73.
        Checked via representative substring matches rather than byte-for-byte to
        avoid whitespace-drift brittleness.
        """
        art = json.loads(mod._BEAR_ARTIFACT_PATH.read_text(encoding="utf-8"))
        obs = mod._build_reporting_obligations(art)
        v = obs[0].verbatim_rule
        assert "Hunters must personally present their bear head and hide" in v
        assert "within five working days after harvest" in v
        assert "prepared for human consumption" in v
        assert v != "Mandatory Bear Inspections & Seals"

    def test_happy_path_source_id(self) -> None:
        """obligation.source.id == 'co-cpw-big-game-2026-brochure'."""
        art = json.loads(mod._BEAR_ARTIFACT_PATH.read_text(encoding="utf-8"))
        obs = mod._build_reporting_obligations(art)
        assert obs[0].source.id == "co-cpw-big-game-2026-brochure"

    def test_happy_path_source_document_type(self) -> None:
        """obligation.source.document_type == 'annual_regulations'."""
        art = json.loads(mod._BEAR_ARTIFACT_PATH.read_text(encoding="utf-8"))
        obs = mod._build_reporting_obligations(art)
        assert obs[0].source.document_type == "annual_regulations"

    def test_happy_path_source_page_reference_ends_with_p73(self) -> None:
        """obligation.source.page_reference ends with ':p73'."""
        art = json.loads(mod._BEAR_ARTIFACT_PATH.read_text(encoding="utf-8"))
        obs = mod._build_reporting_obligations(art)
        page_ref = obs[0].source.page_reference
        assert page_ref is not None, "page_reference should not be None"
        assert page_ref.endswith(":p73"), (
            f"Expected page_reference ending in ':p73'; got {page_ref!r}"
        )

    # --- Fail-loud cases using synthetic flat lists ---

    def test_non_dict_entry_raises(self) -> None:
        """A non-dict entry in the artifact raises RuntimeError."""
        artifact: list = ["not a dict"]  # type: ignore[list-item]
        with pytest.raises(RuntimeError):
            mod._build_reporting_obligations(artifact)

    def test_missing_record_type_raises(self) -> None:
        """An entry missing 'record_type' raises RuntimeError."""
        artifact = [{"region_scope": "STATEWIDE", "kind_hint": "mandatory_inspection"}]
        with pytest.raises(RuntimeError, match="record_type"):
            mod._build_reporting_obligations(artifact)

    def test_unknown_record_type_raises(self) -> None:
        """An entry with record_type='Reporting_Obligation' (misspelled) raises RuntimeError."""
        artifact = [
            {
                "record_type": "Reporting_Obligation",
                "region_scope": "STATEWIDE",
                "kind_hint": "mandatory_inspection",
            }
        ]
        with pytest.raises(RuntimeError, match="Reporting_Obligation"):
            mod._build_reporting_obligations(artifact)

    def test_unknown_combo_raises(self) -> None:
        """Unknown (region_scope, kind_hint) combo raises RuntimeError."""
        artifact = [_make_ro_entry(region_scope="STATEWIDE", kind_hint="novel_thing")]
        with pytest.raises(RuntimeError, match="novel_thing"):
            mod._build_reporting_obligations(artifact)

    def test_missing_verbatim_rule_raises(self) -> None:
        """Entry missing 'verbatim_rule' key raises RuntimeError."""
        entry = _make_ro_entry()
        del entry["verbatim_rule"]
        with pytest.raises(RuntimeError, match="verbatim_rule"):
            mod._build_reporting_obligations([entry])

    def test_missing_region_scope_raises(self) -> None:
        """Entry missing 'region_scope' raises RuntimeError."""
        entry = _make_ro_entry()
        del entry["region_scope"]
        with pytest.raises(RuntimeError, match="region_scope"):
            mod._build_reporting_obligations([entry])

    def test_wrong_source_id_raises(self) -> None:
        """Entry with source_id != _BIG_GAME_CITATION_ID raises RuntimeError."""
        artifact = [_make_ro_entry(source_id="wrong-id")]
        with pytest.raises(RuntimeError, match="wrong-id"):
            mod._build_reporting_obligations(artifact)

    def test_duplicate_ids_raise(self) -> None:
        """Two reporting_obligation entries mapping to the same key raises RuntimeError."""
        artifact = [
            _make_ro_entry(),
            _make_ro_entry(),  # same (region_scope, kind_hint) → duplicate id
        ]
        with pytest.raises(RuntimeError, match="duplicate"):
            mod._build_reporting_obligations(artifact)

    def test_only_non_obligation_entries_returns_empty(self) -> None:
        """Flat list with only section + statewide_rule (no reporting_obligation) returns []."""
        artifact = [
            _make_section_entry("082"),
            _make_section_entry("085"),
            _make_statewide_rule_entry("season_dates_summary"),
        ]
        result = mod._build_reporting_obligations(artifact)
        assert result == []


# ---------------------------------------------------------------------------
# TestCountGuard
# ---------------------------------------------------------------------------


class TestCountGuard:
    """OQ7 row-count guard: exact-match band (1, 1)."""

    def test_band_constant_is_1_1(self) -> None:
        """_REPORTING_OBLIGATION_COUNT_GUARD_BAND == (1, 1)."""
        assert mod._REPORTING_OBLIGATION_COUNT_GUARD_BAND == (1, 1)

    def test_count_1_passes(self) -> None:
        """Count of 1 is within band [1, 1] — no raise."""
        mod._assert_reporting_obligation_count_within_guard(1)  # must not raise

    def test_count_0_raises(self) -> None:
        """Count of 0 is below band → RuntimeError."""
        with pytest.raises(RuntimeError, match="0"):
            mod._assert_reporting_obligation_count_within_guard(0)

    def test_count_2_raises(self) -> None:
        """Count of 2 is above band → RuntimeError."""
        with pytest.raises(RuntimeError, match="2"):
            mod._assert_reporting_obligation_count_within_guard(2)

    def test_count_3_raises(self) -> None:
        """Count of 3 is above band → RuntimeError."""
        with pytest.raises(RuntimeError, match="3"):
            mod._assert_reporting_obligation_count_within_guard(3)


# ---------------------------------------------------------------------------
# TestDocumentTypeGuard
# ---------------------------------------------------------------------------


class TestDocumentTypeGuard:
    """_assert_document_type_allowed: allowed + rejected document_type values."""

    def _citation(self, document_type: str) -> SourceCitation:
        return SourceCitation(
            id="test-citation",
            agency="Colorado Parks and Wildlife",
            title="Test Document",
            url="https://example.com/test.pdf",
            publication_date="2026-03-04",
            document_type=document_type,  # type: ignore[arg-type]
            supersedes=None,
            page_reference=None,
        )

    def test_annual_regulations_allowed(self) -> None:
        """document_type='annual_regulations' does not raise."""
        mod._assert_document_type_allowed(self._citation("annual_regulations"))

    def test_correction_allowed(self) -> None:
        """document_type='correction' does not raise."""
        mod._assert_document_type_allowed(self._citation("correction"))

    def test_gis_layer_raises_value_error(self) -> None:
        """document_type='gis_layer' → ValueError (not RuntimeError).

        The guard raises ValueError matching load_regulation_records.py precedent.
        SourceCitation permits 'gis_layer' as a valid Literal value in the schema,
        so we can construct it directly without model_construct().
        """
        with pytest.raises(ValueError, match="gis_layer"):
            mod._assert_document_type_allowed(self._citation("gis_layer"))

    def test_real_brochure_citation_passes(self) -> None:
        """The actual _load_citation_from_sources_yaml result for the brochure passes."""
        citation = mod._load_citation_from_sources_yaml(mod._BIG_GAME_CITATION_ID)
        mod._assert_document_type_allowed(citation)  # must not raise

    def test_disallowed_raises_value_error_not_runtime_error(self) -> None:
        """The guard raises ValueError, NOT RuntimeError, for disallowed types."""
        citation = self._citation("gis_layer")
        with pytest.raises(ValueError):
            mod._assert_document_type_allowed(citation)
        # Confirm it is specifically ValueError, not RuntimeError
        try:
            mod._assert_document_type_allowed(citation)
        except ValueError:
            pass  # expected
        except RuntimeError:
            pytest.fail("_assert_document_type_allowed raised RuntimeError instead of ValueError")


# ---------------------------------------------------------------------------
# TestNewGuards (Fix 9 additions)
# ---------------------------------------------------------------------------


class TestNewGuards:
    """Tests for guards added in the S06.9 review-fix batch."""

    # --- Fix 4: non-list artifact raises ---

    def test_non_list_artifact_dict_raises(self) -> None:
        """A dict passed as bear_artifact raises RuntimeError naming the type."""
        with pytest.raises(RuntimeError, match="dict"):
            mod._build_reporting_obligations({})  # type: ignore[arg-type]

    def test_non_list_artifact_none_raises(self) -> None:
        """None passed as bear_artifact raises RuntimeError."""
        with pytest.raises(RuntimeError):
            mod._build_reporting_obligations(None)  # type: ignore[arg-type]

    # --- Fix 3: deadline_hint cross-check ---

    def test_deadline_hint_mismatch_raises(self) -> None:
        """An entry whose deadline_hint disagrees with the spec deadline raises RuntimeError."""
        entry = _make_ro_entry()
        entry["deadline_hint"] = "WRONG"  # spec deadline is "5 working days"
        with pytest.raises(RuntimeError, match="deadline_hint"):
            mod._build_reporting_obligations([entry])

    def test_deadline_hint_matching_spec_does_not_raise(self) -> None:
        """An entry whose deadline_hint matches the spec deadline builds fine."""
        entry = _make_ro_entry()
        entry["deadline_hint"] = "5 working days"  # matches spec
        obs = mod._build_reporting_obligations([entry])
        assert len(obs) == 1

    def test_no_deadline_hint_key_does_not_raise(self) -> None:
        """An entry without a deadline_hint key skips the cross-check (guard is optional)."""
        entry = _make_ro_entry()
        # _make_ro_entry does not include deadline_hint — confirm and call
        assert "deadline_hint" not in entry
        obs = mod._build_reporting_obligations([entry])
        assert len(obs) == 1

    # --- _load_citation_from_sources_yaml missing-id guard ---

    def test_load_citation_missing_id_raises(self) -> None:
        """_load_citation_from_sources_yaml raises RuntimeError for a non-existent id."""
        with pytest.raises(RuntimeError, match="nonexistent-id"):
            mod._load_citation_from_sources_yaml("nonexistent-id")

    # --- Fix 6: zero-obligations warning via caplog ---

    def test_zero_obligations_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """An artifact with no reporting_obligation entries logs a WARNING."""
        import logging

        artifact = [
            _make_section_entry("082"),
            _make_statewide_rule_entry("season_dates_summary"),
        ]
        with caplog.at_level(logging.WARNING, logger=mod.__name__):
            result = mod._build_reporting_obligations(artifact)
        assert result == []
        assert any(
            "0 rows" in record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        ), f"Expected a 0-rows WARNING; got: {[r.message for r in caplog.records]}"

    # --- Fix 5: heading-only verbatim_rule warning ---

    def test_heading_only_verbatim_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """An obligation whose verbatim_rule is the heading-only value logs a WARNING."""
        import logging

        entry = _make_ro_entry(verbatim_rule=mod._KNOWN_HEADING_ONLY_VERBATIM)
        with caplog.at_level(logging.WARNING, logger=mod.__name__):
            obs = mod._build_reporting_obligations([entry])
        assert len(obs) == 1
        assert any(
            "heading-only" in record.message
            for record in caplog.records
            if record.levelno == logging.WARNING
        ), f"Expected a heading-only WARNING; got: {[r.message for r in caplog.records]}"

    def test_non_heading_verbatim_does_not_log_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """An obligation with full prose verbatim_rule does NOT log the heading-only WARNING."""
        import logging

        entry = _make_ro_entry(verbatim_rule="Full inspection prose here.")
        with caplog.at_level(logging.WARNING, logger=mod.__name__):
            obs = mod._build_reporting_obligations([entry])
        assert len(obs) == 1
        heading_warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "heading-only" in r.message
        ]
        assert not heading_warnings, (
            f"Unexpected heading-only WARNING for non-heading verbatim_rule: {heading_warnings}"
        )

    def test_live_artifact_does_not_log_heading_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """S06.9.1: the re-extracted artifact's full-prose verbatim_rule does not
        trip the loader's heading-only WARNING gate."""
        import logging

        art = json.loads(mod._BEAR_ARTIFACT_PATH.read_text(encoding="utf-8"))
        with caplog.at_level(logging.WARNING, logger=mod.__name__):
            obs = mod._build_reporting_obligations(art)
        assert len(obs) == 1
        heading_warnings = [
            r for r in caplog.records
            if r.levelno == logging.WARNING and "heading-only" in r.message
        ]
        assert not heading_warnings, f"Unexpected heading-only WARNING: {heading_warnings}"


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------


class TestMain:
    """--dry-run and -v paths exercise build + guard without DB connectivity."""

    def test_dry_run_returns_0(self) -> None:
        """main(['--dry-run']) returns 0."""
        result = mod.main(["--dry-run"])
        assert result == 0

    def test_dry_run_verbose_returns_0(self) -> None:
        """main(['--dry-run', '-v']) returns 0."""
        result = mod.main(["--dry-run", "-v"])
        assert result == 0

    def test_dry_run_does_not_call_db_connect(self) -> None:
        """--dry-run does not open a DB connection."""
        from unittest.mock import MagicMock, patch

        mock_connect = MagicMock()
        with patch("ingestion.lib.db.connect", mock_connect):
            result = mod.main(["--dry-run"])

        assert result == 0
        mock_connect.assert_not_called()

    def test_count_guard_runs_before_connect(self) -> None:
        """Count guard fires before db.connect; if it raises, connect is never called."""
        from unittest.mock import MagicMock, patch

        mock_connect = MagicMock()

        with (
            patch.object(
                mod,
                "_assert_reporting_obligation_count_within_guard",
                side_effect=RuntimeError("guard_boom"),
            ),
            patch("ingestion.lib.db.connect", mock_connect),
        ):
            with pytest.raises(RuntimeError, match="guard_boom"):
                mod.main([])

        mock_connect.assert_not_called()


# ---------------------------------------------------------------------------
# TestNoLibImports
# ---------------------------------------------------------------------------


class TestNoLibImports:
    """Ensure load_reporting_obligations.py imports no sibling state adapter (ADR-005).

    CO→CO imports are permitted; all other state adapters are forbidden.
    Only the PRODUCTION loader source is checked here — test-file imports
    of sibling state modules are fine.
    """

    def test_no_montana_imports(self) -> None:
        """load_reporting_obligations.py must not import from states.montana."""
        source = _loader_source_path().read_text(encoding="utf-8")
        tree = ast.parse(source)

        forbidden_prefixes = ("states.montana", "ingestion.states.montana")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in forbidden_prefixes:
                        assert not alias.name.startswith(prefix), (
                            f"load_reporting_obligations.py has forbidden import: {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for prefix in forbidden_prefixes:
                    assert not module.startswith(prefix), (
                        f"load_reporting_obligations.py has forbidden from-import: from {module}"
                    )

    def test_no_other_state_adapter_imports(self) -> None:
        """load_reporting_obligations.py must not import any non-Colorado state adapter.

        CO→CO imports (states.colorado.*) are permitted; any other state adapter
        is forbidden per ADR-005.
        """
        source = _loader_source_path().read_text(encoding="utf-8")
        tree = ast.parse(source)

        def _offending(module: str) -> bool:
            for root in ("states.", "ingestion.states."):
                if module.startswith(root):
                    sibling = module[len(root):].split(".", 1)[0]
                    if sibling != "colorado":
                        return True
            return False

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not _offending(alias.name), (
                        f"load_reporting_obligations.py imports a non-Colorado state "
                        f"adapter: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not _offending(module), (
                    f"load_reporting_obligations.py imports a non-Colorado state "
                    f"adapter: from {module}"
                )


# ---------------------------------------------------------------------------
# TestNoLayoutTrueRegression
# ---------------------------------------------------------------------------


class TestNoLayoutTrueRegression:
    """ADR-008 paraphrase-prohibition guard: layout=True injects synthetic spaces.

    This loader does not call pdfplumber at all, so this test is always green.
    It locks the invariant for future edits — if someone adds a pdfplumber
    call with layout=True, this test will catch it.
    """

    def test_no_layout_true_kwarg_in_loader(self) -> None:
        """AST walk: no ast.Call in the loader passes a keyword layout=True."""
        source = _loader_source_path().read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg == "layout" and isinstance(kw.value, ast.Constant):
                    assert kw.value.value is not True, (
                        "load_reporting_obligations.py passes layout=True to a call; "
                        "this violates ADR-008 byte-equivalence — remove the kwarg"
                    )
