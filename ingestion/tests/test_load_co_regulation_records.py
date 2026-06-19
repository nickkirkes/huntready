"""Unit tests for states.colorado.load_regulation_records — T3: fixtures + builder behavior.

Covers:
- TestBuildBigGameRecords — big-game sections → regulation_record collapse behavior
- TestBuildBearRecords    — bear sections → regulation_record with correct species mapping

All tests are pure-function / mocked — no real PDF, no DB.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ingestion.lib.schema import SourceCitation
from states.colorado import load_regulation_records as mod


# ---------------------------------------------------------------------------
# Helper factories (module-level)
# ---------------------------------------------------------------------------


def _make_citation() -> SourceCitation:
    """Valid annual_regulations CO brochure citation."""
    return SourceCitation(
        id="co-cpw-big-game-2026-brochure",
        agency="Colorado Parks and Wildlife",
        title="2026 Colorado Big Game Hunting Regulations",
        url="https://spl.cde.state.co.us/artemis/nrserials/nr1431internet/nr14312026internet.pdf",
        publication_date="2026-03-04",
        document_type="annual_regulations",
        supersedes=None,
        page_reference=None,
    )


def _make_bg_section(
    gmu_code: str,
    species_group: str,
    method_group: str = "rifle",
    confidences: tuple[str, ...] = ("high",),
    page: int = 10,
    verbatim: str = "License | GMU | Hunt Code | Dates\n001 | 20 | D-M-020-O1-R | Oct 1-31",
) -> dict:  # type: ignore[type-arg]
    """Synthetic minimal big-game section dict.

    Keys match what _build_big_game_records reads:
    gmu_code, species_group, method_group, page_reference (dict), verbatim_text, rows.
    """
    return {
        "gmu_code": gmu_code,
        "species_group": species_group,
        "method_group": method_group,
        "page_reference": {
            "page_num_1based": page,
            "bbox": None,
            "pdf_filename": "x.pdf",
            "extracted_at": "2026-06-09T00:00:00+00:00",
        },
        "verbatim_text": verbatim,
        "rows": [{"extraction_confidence": c} for c in confidences],
    }


def _make_bear_section(
    gmu_code: str,
    method_group: str = "rifle",
    confidences: tuple[str, ...] = ("high",),
    page: int = 72,
    verbatim: str = "B-E-082-R1-R",
) -> dict:  # type: ignore[type-arg]
    """Synthetic minimal bear section dict.

    Bears use a flat artifact list with record_type discriminator.
    """
    return {
        "record_type": "section",
        "species_group": "black_bear",
        "gmu_code": gmu_code,
        "method_group": method_group,
        "page_reference": {
            "page_num_1based": page,
            "bbox": None,
            "pdf_filename": "x.pdf",
            "extracted_at": "2026-06-09T00:00:00+00:00",
        },
        "verbatim_text": verbatim,
        "rows": [{"extraction_confidence": c} for c in confidences],
    }


def _make_statewide_rule(
    rule_hint: str,
    source_id: str = "co-cpw-big-game-2026-brochure",
) -> dict:  # type: ignore[type-arg]
    """Synthetic bear statewide_rule record."""
    return {
        "record_type": "statewide_rule",
        "rule_hint": rule_hint,
        "source_id": source_id,
    }


# ---------------------------------------------------------------------------
# TestBuildBigGameRecords
# ---------------------------------------------------------------------------


class TestBuildBigGameRecords:
    """Builder behavior: collapse sections by (gmu_code, species_group)."""

    def _logger(self) -> logging.Logger:
        return logging.getLogger("test")

    def test_collapses_multiple_method_sections_into_one_record(self) -> None:
        """3 sections for (020, elk) with different method_groups → exactly 1 record."""
        sections = [
            _make_bg_section("020", "elk", method_group="rifle"),
            _make_bg_section("020", "elk", method_group="archery"),
            _make_bg_section("020", "elk", method_group="muzzleloader"),
        ]
        records = mod._build_big_game_records(sections, _make_citation(), self._logger())
        assert len(records) == 1
        assert records[0].jurisdiction_code == "CO-GMU-20"
        assert records[0].species_group == "elk"

    def test_no_fanout_each_species_own_record(self) -> None:
        """One section per species for GMU 001 → exactly 4 records, no fan-out."""
        sections = [
            _make_bg_section("001", "mule_deer"),
            _make_bg_section("001", "whitetail"),
            _make_bg_section("001", "elk"),
            _make_bg_section("001", "pronghorn"),
        ]
        records = mod._build_big_game_records(sections, _make_citation(), self._logger())
        assert len(records) == 4
        species_set = {r.species_group for r in records}
        assert species_set == {"mule_deer", "whitetail", "elk", "pronghorn"}

    def test_jurisdiction_code_strips_zero_padding(self) -> None:
        """Artifact gmu_code '007' → jurisdiction_code 'CO-GMU-7' (leading zeros stripped)."""
        sections = [_make_bg_section("007", "elk")]
        records = mod._build_big_game_records(sections, _make_citation(), self._logger())
        assert len(records) == 1
        assert records[0].jurisdiction_code == "CO-GMU-7"

    def test_blank_gmu_section_skipped_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A section with blank gmu_code is skipped with a warning; valid section produces a record."""
        blank = _make_bg_section("", "elk", method_group="archery", page=52)
        valid = _make_bg_section("020", "elk")
        sections = [blank, valid]

        with caplog.at_level(logging.WARNING):
            records = mod._build_big_game_records(sections, _make_citation(), self._logger())

        assert len(records) == 1
        assert records[0].jurisdiction_code == "CO-GMU-20"
        # At least one warning about the blank gmu_code must have been emitted.
        warning_texts = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("blank" in msg.lower() or "gmu_code" in msg.lower() for msg in warning_texts), (
            f"Expected a warning about blank gmu_code; got: {warning_texts!r}"
        )

    def test_min_confidence_across_rows_and_sections(self) -> None:
        """MIN over all rows across all sections: high+low → 'low'; high+medium → 'medium'."""
        # Case 1: high + low → low
        sections_hl = [
            _make_bg_section("010", "elk", method_group="rifle", confidences=("high",)),
            _make_bg_section("010", "elk", method_group="archery", confidences=("low",)),
        ]
        records_hl = mod._build_big_game_records(
            sections_hl, _make_citation(), self._logger()
        )
        assert len(records_hl) == 1
        assert records_hl[0].confidence == "low", (
            f"Expected 'low' from high+low mix, got {records_hl[0].confidence!r} "
            "(check pdf.min_tier is used, not lexicographic min)"
        )

        # Case 2: high + medium → medium
        sections_hm = [
            _make_bg_section("011", "elk", method_group="rifle", confidences=("high",)),
            _make_bg_section("011", "elk", method_group="archery", confidences=("medium",)),
        ]
        records_hm = mod._build_big_game_records(
            sections_hm, _make_citation(), self._logger()
        )
        assert len(records_hm) == 1
        assert records_hm[0].confidence == "medium"

    def test_additional_rules_empty_when_no_note_lines(self) -> None:
        """Standard CO pipe-table verbatim (no NOTE:) → additional_rules == []."""
        verbatim = "License | GMU | Hunt Code | Dates\nD-M-020-O1-R | 020 | A | Oct 1-31"
        sections = [_make_bg_section("020", "elk", verbatim=verbatim)]
        records = mod._build_big_game_records(sections, _make_citation(), self._logger())
        assert len(records) == 1
        assert records[0].additional_rules == []

    def test_note_line_extracted_when_present(self) -> None:
        """verbatim_text containing 'NOTE: foo bar' → one VerbatimRule with that text.

        The regex captures everything after NOTE: up to the next NOTE: line,
        an ALL-CAPS header line (3+ chars), or end-of-string. Using a plain
        NOTE at end-of-string ensures the captured body is exactly "foo bar"
        (no continuation content absorbed).
        """
        verbatim = "NOTE: foo bar"
        sections = [_make_bg_section("020", "elk", verbatim=verbatim)]
        records = mod._build_big_game_records(sections, _make_citation(), self._logger())
        assert len(records) == 1
        rules = records[0].additional_rules
        assert len(rules) == 1
        assert rules[0].text == "NOTE: foo bar"

    def test_record_order_deterministic(self) -> None:
        """Building from the same input twice yields identical jurisdiction_code/species ordering."""
        sections = [
            _make_bg_section("020", "elk"),
            _make_bg_section("001", "mule_deer"),
            _make_bg_section("020", "mule_deer"),
            _make_bg_section("001", "elk"),
        ]
        citation = _make_citation()
        logger = self._logger()

        first = [
            (r.jurisdiction_code, r.species_group)
            for r in mod._build_big_game_records(sections, citation, logger)
        ]
        second = [
            (r.jurisdiction_code, r.species_group)
            for r in mod._build_big_game_records(sections, citation, logger)
        ]
        assert first == second, (
            f"Order is non-deterministic: first={first!r}, second={second!r}"
        )


# ---------------------------------------------------------------------------
# TestBuildBearRecords
# ---------------------------------------------------------------------------


class TestBuildBearRecords:
    """Builder behavior for the flat-list CO bear artifact."""

    def _logger(self) -> logging.Logger:
        return logging.getLogger("test")

    def test_filters_to_section_record_type(self) -> None:
        """Artifact with 2 sections + 1 statewide_rule + 1 reporting_obligation → 2 records only."""
        artifact = [
            _make_bear_section("082"),
            _make_bear_section("085"),
            _make_statewide_rule("season_dates_summary"),
            {"record_type": "reporting_obligation", "kind": "harvest_report"},
        ]
        records = mod._build_co_bear_records(artifact, _make_citation(), self._logger())
        assert len(records) == 2

    def test_species_group_is_bear_not_black_bear(self) -> None:
        """Artifact species_group 'black_bear' must produce DB species_group 'bear'."""
        artifact = [_make_bear_section("082")]
        records = mod._build_co_bear_records(artifact, _make_citation(), self._logger())
        assert len(records) == 1
        assert records[0].species_group == "bear", (
            f"Expected species_group='bear', got {records[0].species_group!r}. "
            "The artifact uses 'black_bear'; DB value must be 'bear'."
        )

    def test_collapses_methods_per_gmu(self) -> None:
        """3 bear sections for gmu 082 with different method_groups → 1 record."""
        artifact = [
            _make_bear_section("082", method_group="rifle"),
            _make_bear_section("082", method_group="archery"),
            _make_bear_section("082", method_group="muzzleloader"),
        ]
        records = mod._build_co_bear_records(artifact, _make_citation(), self._logger())
        assert len(records) == 1
        assert records[0].jurisdiction_code == "CO-GMU-82"

    def test_jurisdiction_code_format_bear(self) -> None:
        """Bear gmu_code '082' → jurisdiction_code 'CO-GMU-82' (leading zeros stripped)."""
        artifact = [_make_bear_section("082")]
        records = mod._build_co_bear_records(artifact, _make_citation(), self._logger())
        assert len(records) == 1
        assert records[0].jurisdiction_code == "CO-GMU-82"


# ---------------------------------------------------------------------------
# T4: Guard tests + _JURISDICTION_BINDING_ID_FORMAT 3-test lock
# ---------------------------------------------------------------------------


class TestCountGuard:
    """_assert_count_within_guard: concrete band [278, 517] (±30% of 398)."""

    def test_in_band_passes(self) -> None:
        """398 (the baseline) is inside the band → no raise."""
        mod._assert_count_within_guard(398)  # must not raise

    def test_lower_bound(self) -> None:
        """278 passes; 277 raises RuntimeError."""
        mod._assert_count_within_guard(278)  # boundary — must not raise
        with pytest.raises(RuntimeError, match="count guard failed"):
            mod._assert_count_within_guard(277)

    def test_upper_bound(self) -> None:
        """517 passes; 518 raises RuntimeError."""
        mod._assert_count_within_guard(517)  # boundary — must not raise
        with pytest.raises(RuntimeError, match="count guard failed"):
            mod._assert_count_within_guard(518)


class TestDocumentTypeGuard:
    """_assert_document_type_allowed: allowed + rejected document_type values."""

    def _citation(self, document_type: str) -> SourceCitation:
        return SourceCitation(
            id="test-citation",
            agency="Colorado Parks and Wildlife",
            title="Test",
            url="https://example.com/test.pdf",
            publication_date="2026-03-04",
            document_type=document_type,  # type: ignore[arg-type]
            supersedes=None,
            page_reference=None,
        )

    def test_annual_regulations_allowed(self) -> None:
        """document_type='annual_regulations' → no raise."""
        mod._assert_document_type_allowed(self._citation("annual_regulations"))

    def test_correction_allowed(self) -> None:
        """document_type='correction' → no raise."""
        mod._assert_document_type_allowed(self._citation("correction"))

    def test_gis_layer_raises(self) -> None:
        """document_type='gis_layer' → ValueError naming 'gis_layer'."""
        with pytest.raises(ValueError, match="gis_layer"):
            mod._assert_document_type_allowed(self._citation("gis_layer"))

    def test_rule_change_raises(self) -> None:
        """document_type='rule_change' → ValueError (not in allowed set)."""
        with pytest.raises(ValueError):
            mod._assert_document_type_allowed(self._citation("rule_change"))


class TestStatewideAnchorFlagAndDiscuss:
    """_assert_no_undeclared_statewide_anchors: known hints pass; unknown / STATEWIDE gmu fails."""

    def test_known_bear_hints_produce_no_anchor_no_raise(self) -> None:
        """The 2 known informational hints + regular sections → no raise."""
        bear_artifact = [
            _make_statewide_rule("season_dates_summary"),
            _make_statewide_rule("list_abc_explanation"),
            _make_bear_section("082"),
            _make_bear_section("085"),
        ]
        big_game_artifact = [
            _make_bg_section("020", "elk"),
        ]
        # Must not raise
        mod._assert_no_undeclared_statewide_anchors(big_game_artifact, bear_artifact)

    def test_unknown_bear_hint_raises(self) -> None:
        """A statewide_rule with rule_hint='bear_id_test_required' → ValueError naming the hint."""
        bear_artifact = [
            _make_statewide_rule("bear_id_test_required"),
        ]
        big_game_artifact: list[dict] = []  # type: ignore[type-arg]
        with pytest.raises(ValueError, match="bear_id_test_required"):
            mod._assert_no_undeclared_statewide_anchors(big_game_artifact, bear_artifact)

    def test_big_game_statewide_gmu_raises(self) -> None:
        """A big-game section with gmu_code='STATEWIDE' → ValueError."""
        statewide_section = _make_bg_section("STATEWIDE", "pronghorn")
        big_game_artifact = [statewide_section]
        bear_artifact: list[dict] = []  # type: ignore[type-arg]
        with pytest.raises(ValueError, match="STATEWIDE"):
            mod._assert_no_undeclared_statewide_anchors(big_game_artifact, bear_artifact)

    def test_no_anchors_written_in_v1(self) -> None:
        """Real CO V1 artifacts pass the guard and produce 0 CO-STATEWIDE jurisdiction_codes."""
        extracted_dir = Path(mod.__file__).resolve().parent / "extracted"
        with (extracted_dir / "big-game-2026.json").open() as f:
            big_game_artifact = json.load(f)
        with (extracted_dir / "black-bear-2026.json").open() as f:
            bear_artifact = json.load(f)

        # Guard must not raise on the real artifacts
        mod._assert_no_undeclared_statewide_anchors(big_game_artifact, bear_artifact)

        citation = _make_citation()
        logger = logging.getLogger("test")

        bg_records = mod._build_big_game_records(big_game_artifact, citation, logger)
        bear_records = mod._build_co_bear_records(bear_artifact, citation, logger)
        all_records = bg_records + bear_records

        statewide_records = [
            r for r in all_records if r.jurisdiction_code.startswith("CO-STATEWIDE")
        ]
        assert statewide_records == [], (
            f"Expected 0 CO-STATEWIDE records in V1; got {len(statewide_records)}: "
            f"{[r.jurisdiction_code for r in statewide_records]}"
        )


class TestJurisdictionBindingIdFormat:
    """3-test lock per AC #550: format byte-identical to MT, importable, UPSERT-noop contract."""

    def test_format_byte_identical_to_mt(self) -> None:
        """CO _JURISDICTION_BINDING_ID_FORMAT must equal MT's constant byte-for-byte."""
        from states.montana.load_regulation_records import (
            _JURISDICTION_BINDING_ID_FORMAT as MT_FMT,
        )

        assert mod._JURISDICTION_BINDING_ID_FORMAT == MT_FMT
        assert mod._JURISDICTION_BINDING_ID_FORMAT == (
            "{state}-{jurisdiction_code}-{species_group}-{license_year}-{role}-{geometry_id}"
        )

    def test_constant_importable(self) -> None:
        """_JURISDICTION_BINDING_ID_FORMAT is a non-empty str (the symbol S06.10 imports)."""
        fmt = mod._JURISDICTION_BINDING_ID_FORMAT
        assert isinstance(fmt, str)
        assert len(fmt) > 0

    def test_statewide_anchor_id_upsert_noop_contract(self) -> None:
        """Applying the format for a CO-STATEWIDE-bear scenario yields the expected literal id.

        CO V1 writes 0 such anchors, but the format contract is locked so S06.10
        can re-derive the id byte-identically for any future statewide anchor.
        """
        binding_id = mod._JURISDICTION_BINDING_ID_FORMAT.format(
            state="US-CO",
            jurisdiction_code="CO-STATEWIDE-bear",
            species_group="bear",
            license_year=2026,
            role="primary_unit",
            geometry_id="CO-STATEWIDE-geom",
        )
        assert binding_id == "US-CO-CO-STATEWIDE-bear-bear-2026-primary_unit-CO-STATEWIDE-geom"


# ---------------------------------------------------------------------------
# T5: AST guards, no-layout=True, main() dry-run + atomic mocked-DB
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Helper: loader source path (mirrors test_load_co_restricted_area_verbatim.py)
# ---------------------------------------------------------------------------


def _loader_source_path() -> Path:
    spec = importlib.util.find_spec("states.colorado.load_regulation_records")
    assert spec is not None and spec.origin is not None
    return Path(spec.origin)


# ---------------------------------------------------------------------------
# Helper: mock db.connect context manager (mirrors test_load_co_restricted_area_verbatim.py:83)
# ---------------------------------------------------------------------------


def _make_connect_cm(mock_conn: MagicMock) -> MagicMock:
    """Wrap mock_conn so `with db.connect() as conn:` yields mock_conn."""
    connect_cm = MagicMock()
    connect_cm.__enter__ = MagicMock(return_value=mock_conn)
    connect_cm.__exit__ = MagicMock(return_value=False)
    return connect_cm


# ---------------------------------------------------------------------------
# TestNoLibImports
# ---------------------------------------------------------------------------


class TestNoLibImports:
    """Ensure load_regulation_records.py imports no sibling state adapter (ADR-005).

    CO → CO imports (states.colorado.*) are permitted; all other state adapters
    are forbidden per the ADR-005 state-isolation discipline.  The MT-format
    comparison import in the TEST FILE is fine — only the PRODUCTION loader
    source is checked here.
    """

    def test_no_montana_imports(self) -> None:
        """load_regulation_records.py must not import from states.montana."""
        source = _loader_source_path().read_text(encoding="utf-8")
        tree = ast.parse(source)

        forbidden_prefixes = ("states.montana", "ingestion.states.montana")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in forbidden_prefixes:
                        assert not alias.name.startswith(prefix), (
                            f"load_regulation_records.py has forbidden import: {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for prefix in forbidden_prefixes:
                    assert not module.startswith(prefix), (
                        f"load_regulation_records.py has forbidden from-import: from {module}"
                    )

    def test_no_other_state_adapter_imports(self) -> None:
        """load_regulation_records.py must not import any non-Colorado state adapter.

        CO→CO imports (states.colorado.*) are permitted; any other state adapter
        is forbidden per ADR-005.
        """
        source = _loader_source_path().read_text(encoding="utf-8")
        tree = ast.parse(source)

        def _offending(module: str) -> bool:
            for root in ("states.", "ingestion.states."):
                if module.startswith(root):
                    sibling = module[len(root) :].split(".", 1)[0]
                    if sibling != "colorado":
                        return True
            return False

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not _offending(alias.name), (
                        f"load_regulation_records.py imports a non-Colorado state"
                        f" adapter: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not _offending(module), (
                    f"load_regulation_records.py imports a non-Colorado state"
                    f" adapter: from {module}"
                )


# ---------------------------------------------------------------------------
# TestNoLayoutTrueRegression
# ---------------------------------------------------------------------------


class TestNoLayoutTrueRegression:
    """ADR-008 paraphrase-prohibition guard: layout=True injects synthetic spaces.

    The loader does not call pdfplumber at all, so this is always green.
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
                        "load_regulation_records.py passes layout=True to a call; "
                        "this violates ADR-008 byte-equivalence — remove the kwarg"
                    )


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for main() — dry-run and live-path, all external I/O mocked.

    All four tests load the REAL extraction artifacts (big-game-2026.json and
    black-bear-2026.json) — no stub artifacts — to exercise the builder logic
    against production data.  DB connectivity is mocked throughout.
    """

    def _expected_record_count(self) -> int:
        """Compute the exact record count by calling the builders against the real artifacts.

        This is the canonical truth for the live-path call-count assertion.
        """
        extracted_dir = Path(mod.__file__).resolve().parent / "extracted"
        with (extracted_dir / "big-game-2026.json").open() as f:
            big_game_artifact: list[dict] = json.load(f)  # type: ignore[type-arg]
        with (extracted_dir / "black-bear-2026.json").open() as f:
            bear_artifact: list[dict] = json.load(f)  # type: ignore[type-arg]

        citation = _make_citation()
        logger = logging.getLogger("test-count")
        bg = mod._build_big_game_records(big_game_artifact, citation, logger)
        bear = mod._build_co_bear_records(bear_artifact, citation, logger)
        return len(bg) + len(bear)

    def test_dry_run_skips_db(self) -> None:
        """--dry-run: returns 0 without opening a DB connection."""
        mock_connect = MagicMock()
        with patch("ingestion.lib.db.connect", mock_connect):
            result = mod.main(["--dry-run"])

        assert result == 0
        mock_connect.assert_not_called()

    def test_live_path_upserts_all_records_and_commits(self) -> None:
        """Live path: upsert_regulation_record called once per record; conn.commit once."""
        expected_count = self._expected_record_count()

        mock_conn = MagicMock()
        connect_cm = _make_connect_cm(mock_conn)

        with (
            patch("ingestion.lib.db.connect", return_value=connect_cm),
            patch("ingestion.lib.db.upsert_regulation_record") as mock_upsert,
        ):
            result = mod.main([])

        assert result == 0
        assert mock_upsert.call_count == expected_count, (
            f"expected upsert_regulation_record called {expected_count} times "
            f"(one per record); got {mock_upsert.call_count}"
        )
        mock_conn.commit.assert_called_once()

    def test_atomic_rollback_on_failure(self) -> None:
        """If upsert fails on the 2nd call, main() propagates and commit is NOT called."""
        mock_conn = MagicMock()
        connect_cm = _make_connect_cm(mock_conn)

        call_count = 0

        def _fail_on_second(*_args: object, **_kwargs: object) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("simulated upsert failure on 2nd call")

        with (
            patch("ingestion.lib.db.connect", return_value=connect_cm),
            patch("ingestion.lib.db.upsert_regulation_record", side_effect=_fail_on_second),
        ):
            with pytest.raises(RuntimeError, match="simulated upsert failure"):
                mod.main([])

        mock_conn.commit.assert_not_called()

    def test_count_guard_runs_before_connect(self) -> None:
        """Count guard fires before db.connect; if it raises, connect is never called."""
        mock_connect = MagicMock()

        with (
            patch.object(
                mod, "_assert_count_within_guard", side_effect=RuntimeError("boom")
            ),
            patch("ingestion.lib.db.connect", mock_connect),
        ):
            with pytest.raises(RuntimeError, match="boom"):
                mod.main([])

        mock_connect.assert_not_called()


# ---------------------------------------------------------------------------
# T6: real-artifact regression locks
# ---------------------------------------------------------------------------


class TestRealArtifactRegression:
    """Regression locks against the committed CO extraction artifacts.

    Verified expected values (from task spec):
      - Total records: 398 (352 big-game + 46 bear)
      - Per-species: mule_deer=141, elk=115, pronghorn=77, whitetail=19, bear=46
      - 0 duplicate PKs
      - All jurisdiction_codes match ^CO-GMU-\\d+$
    """

    @staticmethod
    def _build_all() -> tuple[list, list, list]:  # type: ignore[type-arg]
        """Load real artifacts + citation and build both record lists.

        Returns (bg_records, bear_records, all_records).
        """
        extracted_dir = Path(mod.__file__).resolve().parent / "extracted"
        with (extracted_dir / "big-game-2026.json").open() as f:
            bg_artifact: list = json.load(f)
        with (extracted_dir / "black-bear-2026.json").open() as f:
            bear_artifact: list = json.load(f)

        citation = mod._load_citation_from_sources_yaml(mod._BIG_GAME_CITATION_ID)
        logger = logging.getLogger("test-regression")

        bg_records = mod._build_big_game_records(bg_artifact, citation, logger)
        bear_records = mod._build_co_bear_records(bear_artifact, citation, logger)
        return bg_records, bear_records, bg_records + bear_records

    def test_total_record_count_is_398(self) -> None:
        """Both builders together produce exactly 398 records."""
        _, _, all_records = self._build_all()
        assert len(all_records) == 398, (
            f"Expected 398 total records (352 big-game + 46 bear); got {len(all_records)}"
        )

    def test_big_game_builder_count_is_352(self) -> None:
        """Big-game builder alone produces exactly 352 records."""
        bg_records, _, _ = self._build_all()
        assert len(bg_records) == 352, (
            f"Expected 352 big-game records; got {len(bg_records)}"
        )

    def test_bear_builder_count_is_46(self) -> None:
        """Bear builder alone produces exactly 46 records."""
        _, bear_records, _ = self._build_all()
        assert len(bear_records) == 46, (
            f"Expected 46 bear records; got {len(bear_records)}"
        )

    def test_per_species_breakdown(self) -> None:
        """Counter by species_group must match verified breakdown."""
        from collections import Counter

        _, _, all_records = self._build_all()
        breakdown = Counter(r.species_group for r in all_records)
        expected = {
            "mule_deer": 141,
            "elk": 115,
            "pronghorn": 77,
            "whitetail": 19,
            "bear": 46,
        }
        assert dict(breakdown) == expected, (
            f"Per-species breakdown mismatch.\n  expected: {expected}\n  got:      {dict(breakdown)}"
        )

    def test_no_duplicate_primary_keys(self) -> None:
        """All (state, jurisdiction_code, species_group, license_year) tuples are unique."""
        _, _, all_records = self._build_all()
        pks = [(r.state, r.jurisdiction_code, r.species_group, r.license_year) for r in all_records]
        unique_pks = set(pks)
        assert len(unique_pks) == len(pks), (
            f"Duplicate primary keys found: {len(pks) - len(unique_pks)} duplicates "
            f"across {len(pks)} records"
        )

    def test_all_jurisdiction_codes_well_formed(self) -> None:
        """Every jurisdiction_code matches ^CO-GMU-\\d+$ (no zero-padding, no STATEWIDE)."""
        import re

        _, _, all_records = self._build_all()
        pattern = re.compile(r"^CO-GMU-\d+$")
        bad = [r.jurisdiction_code for r in all_records if not pattern.match(r.jurisdiction_code)]
        assert bad == [], (
            f"jurisdiction_codes failing ^CO-GMU-\\d+$ pattern: {bad[:10]!r}"
        )

    def test_all_bear_records_species_group_bear(self) -> None:
        """Every record from the bear builder has species_group='bear' (not 'black_bear')."""
        _, bear_records, _ = self._build_all()
        bad = [r.species_group for r in bear_records if r.species_group != "bear"]
        assert bad == [], (
            f"Bear builder produced non-'bear' species_group values: {bad!r}"
        )

    def test_all_records_license_year_2026_schema_version_2(self) -> None:
        """All records have license_year=2026 and schema_version=2 (anchor invariants)."""
        _, _, all_records = self._build_all()
        bad_year = [r for r in all_records if r.license_year != 2026]
        bad_schema = [r for r in all_records if r.schema_version != 2]
        assert bad_year == [], f"Records with license_year != 2026: {len(bad_year)}"
        assert bad_schema == [], f"Records with schema_version != 2: {len(bad_schema)}"

    def test_real_artifact_build_is_deterministic(self) -> None:
        """Building twice produces identical (jurisdiction_code, species_group, confidence) tuples."""
        _, _, first = self._build_all()
        _, _, second = self._build_all()
        first_tuples = [(r.jurisdiction_code, r.species_group, r.confidence) for r in first]
        second_tuples = [(r.jurisdiction_code, r.species_group, r.confidence) for r in second]
        assert first_tuples == second_tuples, (
            "Build is non-deterministic: first and second runs differ"
        )

    def test_count_within_guard_passes_on_real_artifacts(self) -> None:
        """_assert_count_within_guard(398) does not raise (real total is within [278, 517])."""
        _, _, all_records = self._build_all()
        # Must not raise
        mod._assert_count_within_guard(len(all_records))


# ---------------------------------------------------------------------------
# T6: NOTE-line edge cases (ported from MT TestExtractNoteLines)
# ---------------------------------------------------------------------------


class TestExtractNoteLines:
    """Port of MT's TestExtractNoteLines — regex/logic is byte-identical."""

    def _cite(self) -> SourceCitation:
        return _make_citation()

    def test_single_note_captured_with_prefix_preserved(self) -> None:
        """Single NOTE: line → one VerbatimRule; text starts with 'NOTE: '."""
        text = "Some preamble\nNOTE: This is a single rule.\nMore body."
        rules = mod._extract_note_lines(text, self._cite(), "high")
        assert len(rules) == 1
        assert rules[0].text == "NOTE: This is a single rule. More body."
        assert rules[0].confidence == "high"
        assert rules[0].source == self._cite()

    def test_multi_physical_line_body_collapses_internal_whitespace(self) -> None:
        """Continuation lines in a NOTE body have internal whitespace collapsed to single spaces."""
        text = "NOTE: First line\nsecond line\nthird line\nNOTE: Next rule"
        rules = mod._extract_note_lines(text, self._cite(), "medium")
        assert len(rules) == 2
        assert rules[0].text == "NOTE: First line second line third line"
        assert rules[1].text == "NOTE: Next rule"

    def test_all_caps_line_terminates_note(self) -> None:
        """An ALL-CAPS-like line (3+ chars) terminates the NOTE body."""
        text = (
            "NOTE: Restricted area description here.\n"
            "ARCHERY APPLY EARLY GENERAL HERITAGE LATE OPPORTUNITY"
        )
        rules = mod._extract_note_lines(text, self._cite(), "medium")
        assert len(rules) == 1
        assert rules[0].text == "NOTE: Restricted area description here."

    def test_two_note_lines_produce_two_rules(self) -> None:
        """A following NOTE: line starts a new rule (two rules total)."""
        text = "NOTE: First rule.\nNOTE: Second rule.\nNOTE: Third rule."
        rules = mod._extract_note_lines(text, self._cite(), "medium")
        assert len(rules) == 3
        assert [r.text for r in rules] == [
            "NOTE: First rule.",
            "NOTE: Second rule.",
            "NOTE: Third rule.",
        ]

    def test_empty_body_note_skipped(self) -> None:
        """Bare NOTE: with empty body is skipped; a real NOTE: after it is captured."""
        # The horizontal-only [ \t]* prefix (not \s*) keeps the regex from
        # absorbing the second NOTE: into the first match.
        text = "NOTE:   \n   \nNOTE: Real note"
        rules = mod._extract_note_lines(text, self._cite(), "medium")
        assert len(rules) == 1
        assert rules[0].text == "NOTE: Real note"

    def test_bare_note_at_end_of_string_skipped(self) -> None:
        """NOTE: with only whitespace at end-of-string emits no rule."""
        text = "NOTE:"
        rules = mod._extract_note_lines(text, self._cite(), "medium")
        assert rules == []

    def test_verbatim_with_no_note_returns_empty_list(self) -> None:
        """verbatim_text without any NOTE: line → empty list."""
        text = "No notes here at all. Just prose.\nMore prose."
        rules = mod._extract_note_lines(text, self._cite(), "high")
        assert rules == []


# ---------------------------------------------------------------------------
# T6: jurisdiction-code helper + document-type edge + log summary smoke
# ---------------------------------------------------------------------------


class TestJurisdictionCodeAndDocTypeEdges:
    """Edge cases for _co_gmu_jurisdiction_code, _assert_document_type_allowed, _log_summary."""

    def test_co_gmu_jurisdiction_code_strips_padding_3digit(self) -> None:
        """'082' → 'CO-GMU-82' (three-digit zero-padded input)."""
        assert mod._co_gmu_jurisdiction_code("082") == "CO-GMU-82"

    def test_co_gmu_jurisdiction_code_strips_padding_3digit_007(self) -> None:
        """'007' → 'CO-GMU-7' (leading double zero stripped)."""
        assert mod._co_gmu_jurisdiction_code("007") == "CO-GMU-7"

    def test_co_gmu_jurisdiction_code_single_digit(self) -> None:
        """'7' → 'CO-GMU-7' (no padding to strip)."""
        assert mod._co_gmu_jurisdiction_code("7") == "CO-GMU-7"

    def test_co_gmu_jurisdiction_code_non_numeric_raises(self) -> None:
        """Non-numeric gmu_code (e.g. 'STATEWIDE') raises ValueError via int()."""
        with pytest.raises(ValueError):
            mod._co_gmu_jurisdiction_code("STATEWIDE")

    def test_document_type_emergency_order_raises(self) -> None:
        """document_type='emergency_order' is not in the allowed set → ValueError."""
        citation = SourceCitation(
            id="test",
            agency="CPW",
            title="Test",
            url="https://example.com/test.pdf",
            publication_date="2026-03-04",
            document_type="emergency_order",  # type: ignore[arg-type]
            supersedes=None,
            page_reference=None,
        )
        with pytest.raises(ValueError, match="emergency_order"):
            mod._assert_document_type_allowed(citation)

    def test_log_summary_smoke(self, caplog: pytest.LogCaptureFixture) -> None:
        """_log_summary runs without raising and logs a line containing 'total'."""
        sections = [
            _make_bg_section("020", "elk"),
            _make_bg_section("001", "mule_deer"),
            _make_bear_section("082"),
        ]
        citation = _make_citation()
        logger = logging.getLogger("test-smoke")
        bg = mod._build_big_game_records(sections[:2], citation, logger)
        bear = mod._build_co_bear_records([sections[2]], citation, logger)
        records = bg + bear

        with caplog.at_level(logging.INFO, logger="test-smoke"):
            mod._log_summary(records, logger)

        log_texts = [r.message for r in caplog.records]
        assert any("total" in t.lower() for t in log_texts), (
            f"Expected a log line containing 'total'; got: {log_texts!r}"
        )


# ---------------------------------------------------------------------------
# TestArtifactShapeFailLoud — locks all new fail-loud guards (FIX 1-5)
# ---------------------------------------------------------------------------


class TestArtifactShapeFailLoud:
    """Fail-loud guards in both builders: missing/bad keys raise RuntimeError with context."""

    def _logger(self) -> logging.Logger:
        return logging.getLogger("test-shape")

    # --- FIX 1: bear record_type validation ---

    def test_bear_entry_missing_record_type_raises(self) -> None:
        """Bear artifact entry without 'record_type' key → RuntimeError."""
        artifact = [{"gmu_code": "082", "species_group": "black_bear"}]
        with pytest.raises(RuntimeError, match="record_type"):
            mod._build_co_bear_records(artifact, _make_citation(), self._logger())

    def test_bear_entry_misspelled_record_type_raises(self) -> None:
        """Bear artifact entry with record_type='Section' (misspelled) → RuntimeError naming the value."""
        artifact = [
            {
                "record_type": "Section",  # capital S — unknown value
                "gmu_code": "082",
                "species_group": "black_bear",
            }
        ]
        with pytest.raises(RuntimeError, match="Section"):
            mod._build_co_bear_records(artifact, _make_citation(), self._logger())

    def test_bear_non_dict_entry_raises(self) -> None:
        """Bear artifact entry that is not a dict → RuntimeError naming the index."""
        artifact: list = ["not-a-dict"]  # type: ignore[list-item]
        with pytest.raises(RuntimeError, match=r"artifact\[0\]"):
            mod._build_co_bear_records(artifact, _make_citation(), self._logger())

    # --- FIX 2: big-game missing 'rows' key ---

    def test_big_game_section_missing_rows_raises(self) -> None:
        """Big-game section with no 'rows' key → RuntimeError naming gmu_code and species_group."""
        section = {
            "gmu_code": "020",
            "species_group": "elk",
            "method_group": "rifle",
            "page_reference": {
                "page_num_1based": 10,
                "bbox": None,
                "pdf_filename": "x.pdf",
                "extracted_at": "2026-06-09T00:00:00+00:00",
            },
            "verbatim_text": "some text",
            # 'rows' key intentionally absent
        }
        with pytest.raises(RuntimeError) as exc_info:
            mod._build_big_game_records([section], _make_citation(), self._logger())
        assert "020" in str(exc_info.value), (
            f"Expected gmu_code '020' in error message; got: {exc_info.value}"
        )

    # --- FIX 2: missing 'extraction_confidence' in a row ---

    def test_big_game_row_missing_extraction_confidence_raises(self) -> None:
        """Big-game row missing 'extraction_confidence' → RuntimeError."""
        section = {
            "gmu_code": "020",
            "species_group": "elk",
            "method_group": "rifle",
            "page_reference": {
                "page_num_1based": 10,
                "bbox": None,
                "pdf_filename": "x.pdf",
                "extracted_at": "2026-06-09T00:00:00+00:00",
            },
            "verbatim_text": "some text",
            "rows": [{}],  # missing 'extraction_confidence'
        }
        with pytest.raises(RuntimeError, match="extraction_confidence"):
            mod._build_big_game_records([section], _make_citation(), self._logger())

    # --- FIX 3: min_tier empty list (rows=[]) → RuntimeError naming gmu/species ---

    def test_big_game_empty_rows_raises_with_gmu_context(self) -> None:
        """Big-game section with rows=[] → RuntimeError whose message names the gmu_code."""
        section = {
            "gmu_code": "042",
            "species_group": "elk",
            "method_group": "archery",
            "page_reference": {
                "page_num_1based": 15,
                "bbox": None,
                "pdf_filename": "x.pdf",
                "extracted_at": "2026-06-09T00:00:00+00:00",
            },
            "verbatim_text": "some text",
            "rows": [],  # empty — min_tier raises PdfExtractionError
        }
        with pytest.raises(RuntimeError) as exc_info:
            mod._build_big_game_records([section], _make_citation(), self._logger())
        assert "042" in str(exc_info.value), (
            f"Expected gmu_code '042' in error message; got: {exc_info.value}"
        )

    def test_bear_empty_rows_raises_with_gmu_context(self) -> None:
        """Bear section with rows=[] → RuntimeError whose message names the gmu_code."""
        section = _make_bear_section("082")
        section["rows"] = []  # override to empty — min_tier raises PdfExtractionError
        artifact = [section]
        with pytest.raises(RuntimeError) as exc_info:
            mod._build_co_bear_records(artifact, _make_citation(), self._logger())
        assert "082" in str(exc_info.value), (
            f"Expected gmu_code '082' in error message; got: {exc_info.value}"
        )

    # --- FIX 4 / pre-connect ordering: document_type and statewide guards fire before connect ---

    def test_document_type_guard_runs_before_connect(self) -> None:
        """_assert_document_type_allowed fires before db.connect; connect is never called."""
        mock_connect = MagicMock()

        with (
            patch.object(
                mod,
                "_assert_document_type_allowed",
                side_effect=ValueError("bad doc type"),
            ),
            patch("ingestion.lib.db.connect", mock_connect),
        ):
            with pytest.raises(ValueError, match="bad doc type"):
                mod.main([])

        mock_connect.assert_not_called()

    def test_statewide_guard_runs_before_connect(self) -> None:
        """_assert_no_undeclared_statewide_anchors fires before db.connect; connect is never called."""
        mock_connect = MagicMock()

        with (
            patch.object(
                mod,
                "_assert_no_undeclared_statewide_anchors",
                side_effect=ValueError("undeclared statewide"),
            ),
            patch("ingestion.lib.db.connect", mock_connect),
        ):
            with pytest.raises(ValueError, match="undeclared statewide"):
                mod.main([])

        mock_connect.assert_not_called()


class TestNotePageProvenance:
    """Locks the cubic P2 fix: each NOTE in a multi-section collapsed group is
    attributed to its OWN section's page, not the representative section's page.

    CO V1 has zero NOTE lines, but the loader keeps this path for future safety;
    this test ensures provenance is preserved if NOTEs ever appear on different
    pages within a single (gmu_code, species_group) group.
    """

    def test_notes_keep_per_section_page_reference(self) -> None:
        # Two sections, same (gmu '020', elk), different method_groups AND pages,
        # each carrying a distinct NOTE line.
        sec_p10 = _make_bg_section(
            "020", "elk", method_group="archery", page=10,
            verbatim="NOTE: archery rule on page ten",
        )
        sec_p20 = _make_bg_section(
            "020", "elk", method_group="muzzleloader", page=20,
            verbatim="NOTE: muzzleloader rule on page twenty",
        )
        records = mod._build_big_game_records(
            [sec_p10, sec_p20], _make_citation(), logging.getLogger("test"),
        )
        assert len(records) == 1
        rules = records[0].additional_rules
        assert len(rules) == 2
        # Rules are collected sorted by (page_num_1based, method_group): p10 first.
        page10_ref = mod.pdf.page_reference_to_str(sec_p10["page_reference"])
        page20_ref = mod.pdf.page_reference_to_str(sec_p20["page_reference"])
        assert page10_ref != page20_ref
        assert rules[0].page_reference == page10_ref
        assert rules[1].page_reference == page20_ref
        # And the per-rule source citation carries the matching page (provenance).
        assert rules[0].source.page_reference == page10_ref
        assert rules[1].source.page_reference == page20_ref
