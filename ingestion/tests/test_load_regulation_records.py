"""Unit tests for ``ingestion/states/montana/load_regulation_records.py``.

Coverage:
- TestExtractNoteLines — NOTE: prefixed line capture from DEA verbatim_text
- TestBuildDeaRecords  — DEA section → regulation_record fan-out
- TestBuildBearRecords — bear row → regulation_record with citation lookup
- TestLegalDescriptionWrites — geometry.legal_description matched-array writes
- TestCountGuard — row-count fail-loud guard (OQ7)
- TestMain — main() wiring with mocked DB

The editable install adds ``ingestion/`` to sys.path so ``states.montana.*``
is directly importable, the same way every sibling adapter test does it.
"""

from __future__ import annotations

import json
from unittest.mock import Mock, patch

import pytest

import states.montana.load_regulation_records as lrr
from ingestion.lib.schema import SourceCitation


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_dummy_citation() -> SourceCitation:
    return SourceCitation(
        id="test-citation",
        agency="Test Agency",
        title="Test Title",
        url="https://example.com/test.pdf",
        publication_date="2026-01-01",
        document_type="annual_regulations",
        supersedes=None,
        page_reference="test.pdf:p1",
    )


def _make_dea_section(
    *,
    hd_number: str = "100",
    hd_name: str = "Test HD",
    species_group: str = "deer",
    row_confidences: list[str] | None = None,
    verbatim_text: str = "",
) -> dict:
    """Synthetic minimal DEA section. Only fields read by _build_dea_records."""
    if row_confidences is None:
        row_confidences = ["medium"]
    return {
        "hd_number": hd_number,
        "hd_name": hd_name,
        "species_group": species_group,
        "license_year": 2026,
        "page_reference": {
            "pdf_filename": "test.pdf",
            "page_num_1based": 1,
            "bbox": None,
            "extracted_at": "2026-01-01T00:00:00+00:00",
        },
        "verbatim_text": verbatim_text,
        "rows": [
            {"extraction_confidence": c}
            for c in row_confidences
        ],
    }


# ---------------------------------------------------------------------------
# TestExtractNoteLines
# ---------------------------------------------------------------------------


class TestExtractNoteLines:
    def test_single_note_line(self) -> None:
        text = "Some preamble\nNOTE: This is a single rule.\nMore body."
        citation = _make_dummy_citation()
        rules = lrr._extract_note_lines(text, citation, "high")
        assert len(rules) == 1
        assert rules[0].text == "NOTE: This is a single rule. More body."
        assert rules[0].confidence == "high"
        assert rules[0].source == citation
        assert rules[0].page_reference == citation.page_reference

    def test_multi_note_lines(self) -> None:
        text = "NOTE: First rule.\nNOTE: Second rule.\nNOTE: Third rule."
        citation = _make_dummy_citation()
        rules = lrr._extract_note_lines(text, citation, "medium")
        assert len(rules) == 3
        assert [r.text for r in rules] == [
            "NOTE: First rule.",
            "NOTE: Second rule.",
            "NOTE: Third rule.",
        ]

    def test_multiline_note_continuation_collapses_whitespace(self) -> None:
        text = "NOTE: First line\nsecond line\nthird line\nNOTE: Next rule"
        citation = _make_dummy_citation()
        rules = lrr._extract_note_lines(text, citation, "medium")
        assert len(rules) == 2
        assert rules[0].text == "NOTE: First line second line third line"
        assert rules[1].text == "NOTE: Next rule"

    def test_note_terminated_by_all_caps_header(self) -> None:
        text = (
            "NOTE: Restricted area description here.\n"
            "ARCHERY APPLY EARLY GENERAL HERITAGE LATE OPPORTUNITY"
        )
        citation = _make_dummy_citation()
        rules = lrr._extract_note_lines(text, citation, "medium")
        assert len(rules) == 1
        assert rules[0].text == "NOTE: Restricted area description here."

    def test_no_notes_returns_empty_list(self) -> None:
        text = "No notes here at all. Just prose.\nMore prose."
        rules = lrr._extract_note_lines(text, _make_dummy_citation(), "high")
        assert rules == []

    def test_whitespace_only_body_skipped(self) -> None:
        # Two consecutive NOTE: lines separated by a whitespace-only spacer line.
        # The horizontal-only prefix consume class [ \t]* (instead of \s*) keeps
        # the regex from absorbing the second NOTE: into the first match — the
        # first NOTE has an empty body and is skipped; the second is captured.
        text = "NOTE:   \n   \nNOTE: Real note"
        rules = lrr._extract_note_lines(text, _make_dummy_citation(), "medium")
        assert len(rules) == 1
        assert rules[0].text == "NOTE: Real note"

    def test_bare_note_at_end_of_string_skipped(self) -> None:
        # A NOTE: prefix with empty body at end-of-string emits no rule
        # (defensive guard — VerbatimRule's non-empty-text validator would
        # otherwise raise on construction).
        text = "NOTE:"
        rules = lrr._extract_note_lines(text, _make_dummy_citation(), "medium")
        assert rules == []


# ---------------------------------------------------------------------------
# TestBuildDeaRecords
# ---------------------------------------------------------------------------


class TestBuildDeaRecords:
    def test_deer_fans_out_to_mule_deer_then_whitetail_in_order(self) -> None:
        # Locks the emit order: mule_deer FIRST, whitetail SECOND.  Downstream
        # stories (S03.7 building license_season rows) may depend on this
        # ordering for deterministic comparison against UAT fixtures.
        citation = _make_dummy_citation()
        section = _make_dea_section(
            hd_number="100", species_group="deer",
            row_confidences=["medium", "medium"],
        )
        records = lrr._build_dea_records([section], citation)
        assert len(records) == 2
        assert records[0].species_group == "mule_deer"
        assert records[1].species_group == "whitetail"
        # Both records share jurisdiction_code, confidence, source, additional_rules
        assert records[0].jurisdiction_code == "MT-HD-deer-elk-lion-100"
        assert records[1].jurisdiction_code == "MT-HD-deer-elk-lion-100"
        assert records[0].confidence == records[1].confidence
        assert records[0].source == records[1].source
        assert records[0].additional_rules == records[1].additional_rules

    def test_elk_single_record(self) -> None:
        records = lrr._build_dea_records(
            [_make_dea_section(hd_number="100", species_group="elk")],
            _make_dummy_citation(),
        )
        assert len(records) == 1
        assert records[0].species_group == "elk"
        assert records[0].jurisdiction_code == "MT-HD-deer-elk-lion-100"

    def test_antelope_per_hd_maps_to_pronghorn(self) -> None:
        records = lrr._build_dea_records(
            [_make_dea_section(hd_number="690", species_group="antelope")],
            _make_dummy_citation(),
        )
        assert len(records) == 1
        assert records[0].species_group == "pronghorn"
        assert records[0].jurisdiction_code == "MT-HD-antelope-690"

    def test_antelope_statewide_maps_to_mt_statewide_antelope(self) -> None:
        records = lrr._build_dea_records(
            [_make_dea_section(hd_number="STATEWIDE", species_group="antelope")],
            _make_dummy_citation(),
        )
        assert len(records) == 1
        assert records[0].species_group == "pronghorn"
        assert records[0].jurisdiction_code == "MT-STATEWIDE-antelope"

    def test_confidence_min_tier_trap_case_high_low_returns_low(self) -> None:
        # The lexicographic-min trap: ["high", "low"] sorts to "high" alphabetically
        # because "h" < "l". The min_tier helper uses key=lambda t: t.rank so the
        # actual most-uncertain tier ("low") wins.
        section = _make_dea_section(row_confidences=["high", "low"])
        records = lrr._build_dea_records([section], _make_dummy_citation())
        assert records[0].confidence == "low", (
            "section with rows confidence ['high','low'] must aggregate to 'low' "
            "via tier-rank MIN — not 'high' from lexicographic min()"
        )

    def test_confidence_medium_medium_returns_medium(self) -> None:
        section = _make_dea_section(row_confidences=["medium", "medium"])
        records = lrr._build_dea_records([section], _make_dummy_citation())
        assert records[0].confidence == "medium"

    def test_jurisdiction_code_unknown_species_group_raises(self) -> None:
        # _DEA_SPECIES_FANOUT has only deer/elk/antelope; an unexpected value
        # raises KeyError on the fanout lookup.
        section = _make_dea_section(species_group="lion")  # not in fan-out map
        with pytest.raises(KeyError):
            lrr._build_dea_records([section], _make_dummy_citation())

    def test_jurisdiction_code_elk_statewide_raises(self) -> None:
        # Only pronghorn has a sanctioned MT-STATEWIDE anchor (ADR-018 §3).
        # An elk / mule_deer / whitetail STATEWIDE section would be an
        # undeclared statewide candidate — must fail loud, not silently
        # produce "MT-HD-deer-elk-lion-STATEWIDE".
        with pytest.raises(ValueError, match="STATEWIDE"):
            lrr._dea_jurisdiction_code("elk", "STATEWIDE")
        with pytest.raises(ValueError, match="STATEWIDE"):
            lrr._dea_jurisdiction_code("mule_deer", "STATEWIDE")
        with pytest.raises(ValueError, match="STATEWIDE"):
            lrr._dea_jurisdiction_code("whitetail", "STATEWIDE")

    def test_jurisdiction_code_pronghorn_statewide_succeeds(self) -> None:
        # Confirms the only sanctioned STATEWIDE jurisdiction in V1.
        assert (
            lrr._dea_jurisdiction_code("pronghorn", "STATEWIDE")
            == "MT-STATEWIDE-antelope"
        )

    def test_page_reference_collapsed_to_string(self) -> None:
        section = _make_dea_section(hd_number="124")
        section["page_reference"] = {
            "pdf_filename": "mt-fwp-dea-2026-booklet-2026-04-27.pdf",
            "page_num_1based": 48,
            "bbox": None,
            "extracted_at": "2026-05-08T00:00:00+00:00",
        }
        records = lrr._build_dea_records([section], _make_dummy_citation())
        assert records[0].source.page_reference == (
            "mt-fwp-dea-2026-booklet-2026-04-27.pdf:p48"
        )

    def test_dea_records_carry_state_and_license_year_and_schema_version(self) -> None:
        records = lrr._build_dea_records(
            [_make_dea_section()], _make_dummy_citation(),
        )
        assert records[0].state == "US-MT"
        assert records[0].license_year == 2026
        assert records[0].schema_version == 2

    def test_notes_in_verbatim_text_populate_additional_rules(self) -> None:
        section = _make_dea_section(
            verbatim_text="Some preamble\nNOTE: Be aware of bears.\nMore.",
        )
        records = lrr._build_dea_records([section], _make_dummy_citation())
        # Both deer fan-out records have the SAME note (1 each), since both
        # records share the same section.
        for rec in records:
            assert len(rec.additional_rules) == 1
            assert rec.additional_rules[0].text == "NOTE: Be aware of bears. More."


# ---------------------------------------------------------------------------
# Bear fixtures
# ---------------------------------------------------------------------------


def _make_bear_source(
    *,
    citation_id: str = "mt-fwp-black-bear-2026-booklet",
    document_type: str = "annual_regulations",
) -> dict:
    """Synthetic minimal source dict from the bear artifact's `sources` list."""
    return {
        "id": citation_id,
        "agency": "Montana Fish, Wildlife & Parks",
        "title": "Test Black Bear Title",
        "url": "https://example.com/bear.pdf",
        "publication_date": "2026-04-27",
        "document_type": document_type,
    }


def _make_bear_row(
    *,
    bmu_number: int = 100,
    source_id: str = "mt-fwp-black-bear-2026-booklet",
    supersedes: str | None = None,
    extraction_confidence: str = "medium",
    verbatim_text: str = "",
) -> dict:
    """Synthetic minimal bear row. Only fields read by _build_bear_records."""
    return {
        "bmu_number": bmu_number,
        "source_id": source_id,
        "supersedes": supersedes,
        "extraction_confidence": extraction_confidence,
        "verbatim_text": verbatim_text,
        "page_reference": {
            "pdf_filename": "test.pdf",
            "page_num_1based": 1,
            "bbox": None,
            "extracted_at": "2026-01-01T00:00:00+00:00",
        },
    }


def _make_bear_artifact(
    *,
    sources: list[dict] | None = None,
    rows: list[dict] | None = None,
) -> dict:
    """Synthetic minimal bear artifact. Only fields read by _build_bear_records."""
    if sources is None:
        sources = [_make_bear_source()]
    if rows is None:
        rows = [_make_bear_row()]
    return {"sources": sources, "rows": rows}


# ---------------------------------------------------------------------------
# TestBuildBearRecords
# ---------------------------------------------------------------------------


class TestBuildBearRecords:
    def test_correction_touched_row_uses_correction_citation(self) -> None:
        """A row referencing the correction source_id should produce a record
        whose source carries document_type='correction' + supersedes populated."""
        booklet = _make_bear_source(
            citation_id="mt-fwp-black-bear-2026-booklet",
            document_type="annual_regulations",
        )
        correction = _make_bear_source(
            citation_id="mt-fwp-black-bear-2026-correction-2026-03-18",
            document_type="correction",
        )
        row = _make_bear_row(
            bmu_number=100,
            source_id="mt-fwp-black-bear-2026-correction-2026-03-18",
            supersedes="mt-fwp-black-bear-2026-booklet",
        )
        artifact = _make_bear_artifact(sources=[booklet, correction], rows=[row])
        records = lrr._build_bear_records(artifact)
        assert len(records) == 1
        rec = records[0]
        assert rec.source.id == "mt-fwp-black-bear-2026-correction-2026-03-18"
        assert rec.source.document_type == "correction"
        assert rec.source.supersedes == "mt-fwp-black-bear-2026-booklet"

    def test_booklet_only_row_no_supersedes(self) -> None:
        """Defensive: V1 has no booklet-only rows but the loader should still
        construct a clean record with document_type='annual_regulations' and
        supersedes=None when one is encountered."""
        booklet = _make_bear_source(
            citation_id="mt-fwp-black-bear-2026-booklet",
            document_type="annual_regulations",
        )
        row = _make_bear_row(
            bmu_number=200,
            source_id="mt-fwp-black-bear-2026-booklet",
            supersedes=None,
        )
        artifact = _make_bear_artifact(sources=[booklet], rows=[row])
        records = lrr._build_bear_records(artifact)
        assert records[0].source.document_type == "annual_regulations"
        assert records[0].source.supersedes is None

    def test_unknown_source_id_raises_runtime_error(self) -> None:
        """A row referencing a source_id not in the artifact's `sources` list
        should fail loud."""
        booklet = _make_bear_source(citation_id="known-id")
        row = _make_bear_row(source_id="unknown-id")
        artifact = _make_bear_artifact(sources=[booklet], rows=[row])
        with pytest.raises(RuntimeError, match="unknown source_id"):
            lrr._build_bear_records(artifact)

    def test_missing_sources_key_raises_diagnostic_runtime_error(self) -> None:
        """A bear artifact missing the top-level `sources` key entirely should
        fail loud with a diagnostic naming the file to inspect — not a bare
        KeyError from the dict comprehension."""
        artifact = {"rows": [_make_bear_row()]}  # no "sources" key
        with pytest.raises(RuntimeError, match="missing or invalid 'sources'"):
            lrr._build_bear_records(artifact)

    def test_sources_wrong_type_raises_diagnostic_runtime_error(self) -> None:
        """A bear artifact with `sources` set to a non-list value (e.g. None or
        a dict) should also fail loud — same diagnostic path."""
        artifact = {"sources": None, "rows": [_make_bear_row()]}
        with pytest.raises(RuntimeError, match="missing or invalid 'sources'"):
            lrr._build_bear_records(artifact)

    def test_invalid_extraction_confidence_raises_at_row(self) -> None:
        """ConfidenceTier(...) validates the row's confidence string at-row,
        naming the bad value — mirrors the DEA path so triage doesn't depend
        on Pydantic's downstream Literal validator catching it later."""
        row = _make_bear_row(extraction_confidence="unknown")
        artifact = _make_bear_artifact(rows=[row])
        with pytest.raises(ValueError, match="unknown"):
            lrr._build_bear_records(artifact)

    def test_jurisdiction_code_derived_from_bmu_number(self) -> None:
        row = _make_bear_row(bmu_number=411)
        artifact = _make_bear_artifact(rows=[row])
        records = lrr._build_bear_records(artifact)
        assert records[0].jurisdiction_code == "MT-HD-bear-411"

    def test_bear_species_group_is_bear_not_black_bear(self) -> None:
        """The DB value is `bear`; the artifact's top-level field is
        `black_bear`. Do not confuse them."""
        records = lrr._build_bear_records(_make_bear_artifact())
        assert records[0].species_group == "bear"

    def test_bear_confidence_passes_through(self) -> None:
        """Bear confidence is not aggregated (one row per record) — it passes
        through directly from the row's extraction_confidence. S03.4 already
        demoted correction-touched rows from HIGH to MEDIUM per ADR-017 §4;
        no re-demote here."""
        row = _make_bear_row(extraction_confidence="medium")
        records = lrr._build_bear_records(_make_bear_artifact(rows=[row]))
        assert records[0].confidence == "medium"

    def test_bear_notes_extracted_from_verbatim_text(self) -> None:
        """Bear `verbatim_text` may contain NOTE-style lines; the loader
        captures them into `additional_rules` using the same helper as the
        DEA loader."""
        row = _make_bear_row(
            verbatim_text="Some prose\nNOTE: Quota closure rule applies.",
        )
        records = lrr._build_bear_records(_make_bear_artifact(rows=[row]))
        assert len(records[0].additional_rules) == 1
        assert records[0].additional_rules[0].text == (
            "NOTE: Quota closure rule applies."
        )

    def test_bear_carries_state_and_license_year_and_schema_version(self) -> None:
        records = lrr._build_bear_records(_make_bear_artifact())
        assert records[0].state == "US-MT"
        assert records[0].license_year == 2026
        assert records[0].schema_version == 2

    def test_bear_page_reference_collapsed_to_string(self) -> None:
        row = _make_bear_row()
        row["page_reference"] = {
            "pdf_filename": "mt-fwp-black-bear-2026-booklet-2026-04-27.pdf",
            "page_num_1based": 9,
            "bbox": None,
            "extracted_at": "2026-05-08T00:00:00+00:00",
        }
        records = lrr._build_bear_records(_make_bear_artifact(rows=[row]))
        assert records[0].source.page_reference == (
            "mt-fwp-black-bear-2026-booklet-2026-04-27.pdf:p9"
        )


# ---------------------------------------------------------------------------
# TestLegalDescriptionWrites
# ---------------------------------------------------------------------------


def _make_legal_desc_entry(
    *,
    geometry_id: str = "MT-HD-deer-elk-lion-100-geom",
    verbatim_description: str | None = "Begin at the junction of Route 1.",
) -> dict:
    """Synthetic minimal legal-descriptions `matched` entry."""
    return {
        "geometry_id": geometry_id,
        "geometry_kind": "hunting_district",
        "verbatim_description": verbatim_description,
        "extraction_confidence": "high",
        "page_reference": {
            "pdf_filename": "legal.pdf",
            "page_num_1based": 1,
            "bbox": None,
            "extracted_at": "2026-01-01T00:00:00+00:00",
        },
    }


def _make_legal_desc_artifact(
    *,
    matched: list[dict] | None = None,
    unmatched: list[dict] | None = None,
    unlinked: list[dict] | None = None,
) -> dict:
    """Synthetic minimal legal-descriptions artifact."""
    if matched is None:
        matched = [_make_legal_desc_entry()]
    return {
        "source_id": "mt-fwp-legal-descriptions-2026-2027",
        "extracted_at": "2026-01-01T00:00:00+00:00",
        "matched": matched,
        "unmatched": unmatched or [],
        "unlinked": unlinked or [],
    }


class TestLegalDescriptionWrites:
    def test_normal_text_passed_through(self) -> None:
        entry = _make_legal_desc_entry(
            geometry_id="MT-HD-deer-elk-lion-100-geom",
            verbatim_description="Begin at the junction of Route 1.",
        )
        artifact = _make_legal_desc_artifact(matched=[entry])
        writes = lrr._legal_description_writes(artifact)
        assert writes == [
            ("MT-HD-deer-elk-lion-100-geom", "Begin at the junction of Route 1."),
        ]

    def test_empty_string_becomes_none(self) -> None:
        entry = _make_legal_desc_entry(verbatim_description="")
        writes = lrr._legal_description_writes(
            _make_legal_desc_artifact(matched=[entry]),
        )
        assert writes[0][1] is None

    def test_whitespace_only_becomes_none(self) -> None:
        entry = _make_legal_desc_entry(verbatim_description="   \n  \t  ")
        writes = lrr._legal_description_writes(
            _make_legal_desc_artifact(matched=[entry]),
        )
        assert writes[0][1] is None

    def test_text_is_stripped(self) -> None:
        entry = _make_legal_desc_entry(
            verbatim_description="  Real description.  \n",
        )
        writes = lrr._legal_description_writes(
            _make_legal_desc_artifact(matched=[entry]),
        )
        assert writes[0][1] == "Real description."

    def test_unmatched_array_ignored(self) -> None:
        """`unmatched` and `unlinked` entries are NEVER written. The loader
        is a pure consumer of the `matched` array."""
        artifact = _make_legal_desc_artifact(
            matched=[],
            unmatched=[{"some": "unmatched-stuff"}],
            unlinked=[{"some": "unlinked-stuff"}],
        )
        writes = lrr._legal_description_writes(artifact)
        assert writes == []

    def test_preserves_source_order(self) -> None:
        entries = [
            _make_legal_desc_entry(geometry_id=f"id-{i}", verbatim_description=f"d{i}")
            for i in range(3)
        ]
        writes = lrr._legal_description_writes(
            _make_legal_desc_artifact(matched=entries),
        )
        ids = [w[0] for w in writes]
        assert ids == ["id-0", "id-1", "id-2"]


# ---------------------------------------------------------------------------
# TestCountGuard
# ---------------------------------------------------------------------------


class TestCountGuard:
    def test_count_within_range_passes(self) -> None:
        # Actual artifact-derived count
        lrr._assert_count_within_guard(436)
        # Lower bound int(514 * 0.70) = 359
        lrr._assert_count_within_guard(359)
        # Upper bound int(514 * 1.30) = 668
        lrr._assert_count_within_guard(668)

    def test_count_below_lower_raises(self) -> None:
        with pytest.raises(RuntimeError, match="count guard failed"):
            lrr._assert_count_within_guard(358)

    def test_count_above_upper_raises(self) -> None:
        with pytest.raises(RuntimeError, match="count guard failed"):
            lrr._assert_count_within_guard(669)

    def test_zero_rows_raises(self) -> None:
        """Catastrophic regression: zero rows must fail loud."""
        with pytest.raises(RuntimeError, match="count guard failed"):
            lrr._assert_count_within_guard(0)

    def test_error_message_mentions_acceptable_range(self) -> None:
        with pytest.raises(RuntimeError) as exc_info:
            lrr._assert_count_within_guard(0)
        msg = str(exc_info.value)
        assert "359-668" in msg
        assert "514" in msg

    def test_legal_desc_count_within_range_passes(self) -> None:
        # Actual artifact baseline
        lrr._assert_legal_desc_count_within_guard(228)
        # Lower bound int(228 * 0.70) = 159
        lrr._assert_legal_desc_count_within_guard(159)
        # Upper bound int(228 * 1.30) = 296
        lrr._assert_legal_desc_count_within_guard(296)

    def test_legal_desc_count_below_lower_raises(self) -> None:
        with pytest.raises(RuntimeError, match="legal_description count"):
            lrr._assert_legal_desc_count_within_guard(158)

    def test_legal_desc_count_above_upper_raises(self) -> None:
        with pytest.raises(RuntimeError, match="legal_description count"):
            lrr._assert_legal_desc_count_within_guard(297)

    def test_legal_desc_count_zero_raises(self) -> None:
        """Catastrophic regression in extract_legal_descriptions.py: zero
        matched entries must fail loud before any DB writes."""
        with pytest.raises(RuntimeError, match="legal_description count"):
            lrr._assert_legal_desc_count_within_guard(0)


# ---------------------------------------------------------------------------
# TestMain — integration test with mocked DB
# ---------------------------------------------------------------------------


def _make_mock_conn() -> tuple[Mock, Mock]:
    """Construct a psycopg3-style mock connection + cursor with CM wiring.

    Mirrors the helper pattern from test_load_state_boundary.py.
    """
    mock_cursor = Mock()
    mock_cursor.rowcount = 1  # default: UPDATE matches one row (success path)

    mock_cursor_cm = Mock()
    mock_cursor_cm.__enter__ = Mock(return_value=mock_cursor)
    mock_cursor_cm.__exit__ = Mock(return_value=None)

    mock_conn = Mock()
    mock_conn.cursor = Mock(return_value=mock_cursor_cm)
    return mock_conn, mock_cursor


def _make_connect_cm(mock_conn: Mock) -> Mock:
    """Wrap a mock connection in a context manager so `with db.connect() as c`
    yields it."""
    cm = Mock()
    cm.__enter__ = Mock(return_value=mock_conn)
    cm.__exit__ = Mock(return_value=None)
    return cm


class TestMain:
    def test_main_dry_run_succeeds_without_db(self) -> None:
        """A dry-run must NOT call db.connect — exit 0 with no DB interaction."""
        with patch.object(lrr.db, "connect") as mock_connect:
            exit_code = lrr.main(["--dry-run"])
        assert exit_code == 0
        mock_connect.assert_not_called()

    def test_main_full_flow_commits_after_writes(self) -> None:
        """main([]) opens the connection, calls upsert_regulation_record for
        each record + update_legal_description for each tuple, then commits
        exactly once."""
        mock_conn, _ = _make_mock_conn()
        connect_cm = _make_connect_cm(mock_conn)
        with (
            patch.object(lrr.db, "connect", return_value=connect_cm),
            patch.object(lrr.db, "upsert_regulation_record") as mock_upsert,
            patch.object(lrr.db, "update_legal_description") as mock_update,
        ):
            exit_code = lrr.main([])
        assert exit_code == 0
        mock_conn.commit.assert_called_once()
        # 436 regulation_records (artifact-derived) + 228 legal_description
        # updates; verify both helpers were invoked.
        assert mock_upsert.call_count > 0
        assert mock_update.call_count > 0

    def test_main_real_artifacts_produce_expected_counts(self) -> None:
        """Lock the artifact-derived row counts. If the artifacts change in
        a way that shifts these numbers, this test fails loud — catches
        catastrophic regressions in the extraction pipeline."""
        with (
            patch.object(lrr.db, "connect") as mock_connect,
            patch.object(lrr.db, "upsert_regulation_record"),
            patch.object(lrr.db, "update_legal_description"),
        ):
            # Use dry-run to avoid hitting db.connect at all.
            exit_code = lrr.main(["--dry-run"])
        assert exit_code == 0
        mock_connect.assert_not_called()

        # Rebuild records directly to assert counts (the dry-run path doesn't
        # expose them, but we re-derive them via the same helpers).
        dea = json.loads(lrr._DEA_ARTIFACT.read_text())
        bear = json.loads(lrr._BEAR_ARTIFACT.read_text())
        legal = json.loads(lrr._LEGAL_DESC_ARTIFACT.read_text())
        dea_citation = lrr._load_citation_from_sources_yaml(lrr._DEA_CITATION_ID)
        records = (
            lrr._build_dea_records(dea, dea_citation)
            + lrr._build_bear_records(bear)
        )
        # Expected: 129×2 (deer fan-out) + 112 (elk) + 31 (antelope) + 35 (bear) = 436
        assert len(records) == 436, (
            f"regulation_record count drift detected: expected 436, got {len(records)}. "
            "Investigate the DEA / Bear extraction artifacts."
        )
        # Expected: 228 matched legal-description entries
        assert len(legal["matched"]) == 228

        # By species_group breakdown
        from collections import Counter
        sg = Counter(r.species_group for r in records)
        assert sg == {
            "mule_deer": 129,
            "whitetail": 129,
            "elk": 112,
            "pronghorn": 31,
            "bear": 35,
        }

    def test_main_count_guard_raises_on_truncated_artifact(self) -> None:
        """If the count guard fires (e.g., DEA artifact loads partially or
        the test monkey-patches _build_dea_records to return [] for the call),
        main() must NOT commit. The guard runs before legal_writes are built
        and before any DB connection."""
        with (
            patch.object(lrr, "_build_dea_records", return_value=[]),
            patch.object(lrr, "_build_bear_records", return_value=[]),
            patch.object(lrr.db, "connect") as mock_connect,
        ):
            with pytest.raises(RuntimeError, match="count guard failed"):
                lrr.main([])
        # Guard fires before DB; connect must not have been called.
        mock_connect.assert_not_called()
