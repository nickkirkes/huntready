"""Unit tests for ``ingestion/states/montana/load_reporting_obligations.py``.

Coverage:
- TestNoLibImports               — state-agnostic-clean AST guard (bidirectional)
- TestBuildReportingObligations  — artifact → 3 ReportingObligation entity rows
- TestBuildRegulationReportingLinks — artifact + obligations → 70 link rows
- TestCountGuards                — OQ7 row-count bands (fire BEFORE db.connect())
- TestMain                       — dry-run smoke + guard fires pre-connect + rollback
- TestDispatchDictDriftGuard     — V1 belt-and-suspenders for the slug-encoded
                                   UPSERT semantic-drift risk; see Q19 in
                                   docs/open-questions.md for the project-wide
                                   fix planned pre-M2

The editable install adds ``ingestion/`` to sys.path so ``states.montana.*``
is directly importable, the same way every sibling adapter test does it.
"""

from __future__ import annotations

import ast
import json
import logging
from pathlib import Path
from unittest.mock import Mock, patch

import pydantic
import psycopg
import pytest

import states.montana.load_reporting_obligations as lro
from ingestion.lib.schema import ReportingObligation
from states.montana.load_reporting_obligations import (
    _assert_regulation_reporting_count_within_guard,
    _assert_reporting_obligation_count_within_guard,
    _build_regulation_reporting_links,
    _build_reporting_obligations,
    main,
)


# ---------------------------------------------------------------------------
# Shared path constants
# ---------------------------------------------------------------------------

_REAL_ARTIFACT_PATH = (
    Path(__file__).resolve().parent.parent
    / "states" / "montana" / "extracted" / "black-bear-2026.json"
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_bear_artifact() -> dict:
    return json.loads(_REAL_ARTIFACT_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def real_obligations(real_bear_artifact: dict) -> list[ReportingObligation]:
    return _build_reporting_obligations(real_bear_artifact)


# ---------------------------------------------------------------------------
# Synthetic artifact helpers
# ---------------------------------------------------------------------------


def _make_minimal_artifact(
    *,
    region_scope: str = "STATEWIDE",
    kind_hint: str = "harvest_report",
    source_id: str = "mt-fwp-black-bear-2026-booklet",
    verbatim_rule: str = "Some verbatim text.",
    page_reference: dict | None = None,
) -> dict:
    """Build a minimal bear artifact with one reporting_obligation entry."""
    if page_reference is None:
        page_reference = {
            "bbox": None,
            "extracted_at": "2026-05-08T00:00:00+00:00",
            "page_num_1based": 7,
            "pdf_filename": "mt-fwp-black-bear-2026-booklet-2026-04-27.pdf",
        }
    return {
        "reporting_obligations": [
            {
                "region_scope": region_scope,
                "kind_hint": kind_hint,
                "source_id": source_id,
                "verbatim_rule": verbatim_rule,
                "page_reference": page_reference,
                "deadline_hint": "48 hours",
                "extraction_confidence": "medium",
                "source_publication_date": "2026-04-27",
            }
        ],
        "sources": [
            {
                "id": "mt-fwp-black-bear-2026-booklet",
                "agency": "Montana Fish, Wildlife & Parks",
                "title": "Black Bear Hunting Regulations 2026",
                "url": "https://fwp.mt.gov/binaries/content/assets/fwp/hunt/regulations/2026/2026-black-bear-final-for-web.pdf",
                "publication_date": "2026-04-27",
                "document_type": "annual_regulations",
            }
        ],
        "rows": [],
    }


def _make_mock_conn() -> tuple[Mock, Mock]:
    """Construct a psycopg3-style mock connection + cursor with CM wiring."""
    mock_cursor = Mock()
    mock_cursor.rowcount = 1

    mock_cursor_cm = Mock()
    mock_cursor_cm.__enter__ = Mock(return_value=mock_cursor)
    mock_cursor_cm.__exit__ = Mock(return_value=None)

    mock_conn = Mock()
    mock_conn.cursor = Mock(return_value=mock_cursor_cm)
    return mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# TestNoLibImports
# ---------------------------------------------------------------------------


class TestNoLibImports:
    """State-agnostic-clean AST guard (bidirectional).

    ``load_reporting_obligations.py`` is a state adapter — it may import only
    from ``ingestion.lib.*``.  The reverse also holds: ``ingestion.lib.db``
    must NOT import from this state adapter.
    """

    def _parse_adapter(self) -> ast.Module:
        source_path = Path(lro.__file__)
        return ast.parse(source_path.read_text(encoding="utf-8"))

    def test_no_sibling_state_adapter_imports(self) -> None:
        """No imports from any other Montana adapter or sibling state."""
        tree = self._parse_adapter()
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                # Block any import from states.montana.* (other adapters)
                if "states.montana" in module and "load_reporting_obligations" not in module:
                    violations.append(
                        f"line {node.lineno}: cross-adapter import from {module!r}"
                    )
                # Block cross-state imports
                if "states.colorado" in module or "states.wyoming" in module:
                    violations.append(
                        f"line {node.lineno}: cross-state import from {module!r}"
                    )
        assert not violations, (
            "load_reporting_obligations.py has forbidden cross-adapter imports:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_no_relative_imports(self) -> None:
        """No relative imports (``from .`` or ``from ..``)."""
        tree = self._parse_adapter()
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if node.level and node.level > 0:
                    violations.append(
                        f"line {node.lineno}: relative import (level={node.level})"
                    )
        assert not violations, (
            "load_reporting_obligations.py uses relative imports:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_only_lib_db_public_api_imported(self) -> None:
        """All ``from ingestion.lib.db import`` must use only public names."""
        tree = self._parse_adapter()
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "ingestion.lib.db":
                    for alias in node.names:
                        if alias.name.startswith("_"):
                            violations.append(
                                f"line {node.lineno}: private name {alias.name!r} "
                                f"imported from ingestion.lib.db"
                            )
        assert not violations, (
            "load_reporting_obligations.py leaks private ingestion.lib.db names:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_db_lib_does_not_import_from_adapter(self) -> None:
        """Reverse check: ingestion/lib/db.py must NOT import from this adapter.

        State-agnostic posture is bidirectional — lib must not depend on adapters.
        """
        db_path = Path(lro.__file__).parent.parent.parent / "ingestion" / "lib" / "db.py"
        tree = ast.parse(db_path.read_text(encoding="utf-8"))
        violations: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if "load_reporting_obligations" in module:
                    violations.append(
                        f"line {node.lineno}: db.py imports from state adapter {module!r}"
                    )
        assert not violations, (
            "ingestion/lib/db.py imports from state adapter (bidirectional violation):\n"
            + "\n".join(f"  - {v}" for v in violations)
        )


# ---------------------------------------------------------------------------
# TestBuildReportingObligations
# ---------------------------------------------------------------------------


class TestBuildReportingObligations:
    def test_builds_three_rows_from_real_artifact(
        self, real_bear_artifact: dict
    ) -> None:
        obligations = _build_reporting_obligations(real_bear_artifact)
        assert len(obligations) == 3

    def test_three_rows_cover_all_dispatch_keys(
        self, real_obligations: list[ReportingObligation]
    ) -> None:
        ids = {ob.id for ob in real_obligations}
        assert "mt-bear-harvest-report-48hr-statewide" in ids
        assert "mt-bear-tooth-submission-r1-10day" in ids
        assert "mt-bear-hide-skull-r2to7-10day" in ids

    def test_statewide_harvest_report_fields(
        self, real_obligations: list[ReportingObligation]
    ) -> None:
        ob = next(
            o for o in real_obligations
            if o.id == "mt-bear-harvest-report-48hr-statewide"
        )
        assert ob.id == "mt-bear-harvest-report-48hr-statewide"
        assert ob.kind == "harvest_report"
        assert ob.deadline == "48 hours"
        assert ob.deadline_hours == 48
        assert ob.submission_method == "phone"
        assert ob.submission_url == "https://fwp.mt.gov"
        assert ob.submission_phone == "1-877-FWPWILD"
        assert ob.applies_to_regions is None
        assert ob.what_to_present is None

    def test_r1_tooth_submission_fields(
        self, real_obligations: list[ReportingObligation]
    ) -> None:
        ob = next(
            o for o in real_obligations
            if o.id == "mt-bear-tooth-submission-r1-10day"
        )
        assert ob.applies_to_regions == ["R1"]
        assert ob.what_to_present == ["both premolar teeth"]
        assert ob.submission_method == "agency_office"
        assert ob.deadline_hours == 240
        assert ob.submission_url is None
        assert ob.submission_phone is None

    def test_r2to7_hide_skull_fields(
        self, real_obligations: list[ReportingObligation]
    ) -> None:
        ob = next(
            o for o in real_obligations
            if o.id == "mt-bear-hide-skull-r2to7-10day"
        )
        assert ob.applies_to_regions == ["R2", "R3", "R4", "R5", "R6", "R7"]
        assert ob.what_to_present == ["hide", "skull"]
        assert ob.submission_method == "in_person_check_station"

    def test_verbatim_rule_preserved_byte_faithful(
        self, real_bear_artifact: dict, real_obligations: list[ReportingObligation]
    ) -> None:
        """verbatim_rule must be byte-equal to the artifact value — no collapse."""
        raw_by_scope = {
            entry["region_scope"]: entry["verbatim_rule"]
            for entry in real_bear_artifact["reporting_obligations"]
        }
        scope_by_id = {
            "mt-bear-harvest-report-48hr-statewide": "STATEWIDE",
            "mt-bear-tooth-submission-r1-10day": "R1",
            "mt-bear-hide-skull-r2to7-10day": "R2-7",
        }
        for ob in real_obligations:
            scope = scope_by_id[ob.id]
            expected = raw_by_scope[scope]
            assert ob.verbatim_rule == expected, (
                f"verbatim_rule for {ob.id!r} does not match artifact byte-for-byte"
            )

    def test_unknown_region_scope_raises(self) -> None:
        artifact = _make_minimal_artifact(
            region_scope="R8",
            kind_hint="harvest_report",
        )
        with pytest.raises(RuntimeError, match=r"unknown reporting_obligation combo"):
            _build_reporting_obligations(artifact)

    def test_unknown_kind_hint_raises(self) -> None:
        artifact = _make_minimal_artifact(
            region_scope="STATEWIDE",
            kind_hint="bogus_kind",
        )
        with pytest.raises(RuntimeError, match=r"unknown reporting_obligation combo"):
            _build_reporting_obligations(artifact)

    def test_missing_source_id_raises(self) -> None:
        artifact = _make_minimal_artifact(source_id="nope")
        with pytest.raises(RuntimeError, match=r"unknown source_id"):
            _build_reporting_obligations(artifact)

    def test_source_entry_missing_id_key_raises_with_diagnostic(self) -> None:
        """A source entry missing the 'id' key fails loud with index + keys present.

        Defensive guard against opaque KeyError from the sources_by_id
        comprehension. The reviewer flagged this site in cubic-review round 4
        (2026-05-21).
        """
        artifact = _make_minimal_artifact()
        # Drop the "id" key from the single source entry
        del artifact["sources"][0]["id"]
        with pytest.raises(
            RuntimeError,
            match=r"sources\[0\] missing required key 'id'",
        ):
            _build_reporting_obligations(artifact)

    def test_source_entry_not_a_dict_raises_with_diagnostic(self) -> None:
        """A non-dict source entry fails loud naming the index + type."""
        artifact = _make_minimal_artifact()
        artifact["sources"][0] = "not a dict"  # type: ignore[index]
        with pytest.raises(
            RuntimeError,
            match=r"sources\[0\] is not a dict.*got str",
        ):
            _build_reporting_obligations(artifact)

    def test_obligation_entry_not_a_dict_raises_with_diagnostic(self) -> None:
        """A non-dict reporting_obligations entry fails loud naming the index + type."""
        artifact = _make_minimal_artifact()
        artifact["reporting_obligations"][0] = "not a dict"  # type: ignore[index]
        with pytest.raises(
            RuntimeError,
            match=r"reporting_obligations\[0\] is not a dict.*got str",
        ):
            _build_reporting_obligations(artifact)

    def test_obligation_entry_missing_required_key_raises_with_diagnostic(
        self,
    ) -> None:
        """A reporting_obligations entry missing a required key fails loud."""
        artifact = _make_minimal_artifact()
        del artifact["reporting_obligations"][0]["verbatim_rule"]
        with pytest.raises(
            RuntimeError,
            match=(
                r"reporting_obligations\[0\] missing required key "
                r"'verbatim_rule'"
            ),
        ):
            _build_reporting_obligations(artifact)

    def test_source_dict_missing_required_citation_field_raises_with_diagnostic(
        self,
    ) -> None:
        """SourceCitation construction fails loud naming the bad source_id + missing key.

        Defensive guard against opaque KeyError when source_dict has the 'id'
        key (so the comprehension succeeds) but is missing a required
        SourceCitation field like 'agency'.
        """
        artifact = _make_minimal_artifact()
        # Drop "agency" — required by SourceCitation
        del artifact["sources"][0]["agency"]
        with pytest.raises(
            RuntimeError,
            match=(
                r"source entry id='mt-fwp-black-bear-2026-booklet' missing "
                r"required key 'agency'"
            ),
        ):
            _build_reporting_obligations(artifact)

    def test_missing_reporting_obligations_key_raises(self) -> None:
        with pytest.raises(RuntimeError, match=r"reporting_obligations"):
            _build_reporting_obligations({})

    def test_missing_sources_key_raises(self) -> None:
        with pytest.raises(RuntimeError, match=r"sources"):
            _build_reporting_obligations(
                {
                    "reporting_obligations": [
                        {
                            "region_scope": "STATEWIDE",
                            "kind_hint": "harvest_report",
                            "source_id": "x",
                            "verbatim_rule": "text",
                            "page_reference": {
                                "bbox": None,
                                "extracted_at": "2026-05-08T00:00:00+00:00",
                                "page_num_1based": 7,
                                "pdf_filename": "test.pdf",
                            },
                            "deadline_hint": "48 hours",
                            "extraction_confidence": "medium",
                            "source_publication_date": "2026-04-27",
                        }
                    ]
                    # no "sources" key
                }
            )

    def test_no_confidence_attribute(
        self, real_obligations: list[ReportingObligation]
    ) -> None:
        """Pydantic extra='forbid' — confidence is not on the model."""
        for ob in real_obligations:
            assert not hasattr(ob, "confidence"), (
                f"ReportingObligation unexpectedly has a 'confidence' attribute on {ob.id!r}"
            )

    def test_pydantic_rejects_confidence_field(self) -> None:
        """Constructing ReportingObligation with confidence= raises ValidationError."""
        from ingestion.lib.schema import SourceCitation
        citation = SourceCitation(
            id="mt-fwp-black-bear-2026-booklet",
            agency="Montana FWP",
            title="Black Bear Regulations 2026",
            url="https://fwp.mt.gov/bear.pdf",
            publication_date="2026-04-27",
            document_type="annual_regulations",
        )
        with pytest.raises(pydantic.ValidationError):
            ReportingObligation(  # type: ignore[call-arg]
                id="mt-bear-test",
                kind="harvest_report",
                deadline="48 hours",
                deadline_hours=48,
                submission_method="phone",
                verbatim_rule="Some text.",
                source=citation,
                confidence="medium",  # forbidden extra field
            )

    def test_cwd_sample_kind_uses_schema_literal(self) -> None:
        """'cwd_sample' is the correct schema literal; 'cwd_sampling' is not."""
        from ingestion.lib.schema import SourceCitation
        citation = SourceCitation(
            id="mt-fwp-black-bear-2026-booklet",
            agency="Montana FWP",
            title="Black Bear Regulations 2026",
            url="https://fwp.mt.gov/bear.pdf",
            publication_date="2026-04-27",
            document_type="annual_regulations",
        )
        base_kwargs = dict(
            id="mt-bear-cwd-test",
            deadline="immediately",
            deadline_hours=None,
            submission_method="agency_office",
            verbatim_rule="CWD sample required.",
            source=citation,
        )
        # Valid literal must construct without error
        ob = ReportingObligation(kind="cwd_sample", **base_kwargs)  # type: ignore[arg-type]
        assert ob.kind == "cwd_sample"

        # Epic narrative drift: 'cwd_sampling' must be rejected
        with pytest.raises(pydantic.ValidationError):
            ReportingObligation(kind="cwd_sampling", **base_kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# TestBuildRegulationReportingLinks
# ---------------------------------------------------------------------------


class TestBuildRegulationReportingLinks:
    def test_link_count_total_70(
        self,
        real_obligations: list[ReportingObligation],
        real_bear_artifact: dict,
    ) -> None:
        links = _build_regulation_reporting_links(real_obligations, real_bear_artifact)
        assert len(links) == 70

    def test_link_distribution_35_14_21(
        self,
        real_obligations: list[ReportingObligation],
        real_bear_artifact: dict,
    ) -> None:
        links = _build_regulation_reporting_links(real_obligations, real_bear_artifact)
        from collections import Counter
        dist = Counter(link.reporting_obligation_id for link in links)
        assert dist["mt-bear-harvest-report-48hr-statewide"] == 35
        assert dist["mt-bear-tooth-submission-r1-10day"] == 14
        assert dist["mt-bear-hide-skull-r2to7-10day"] == 21

    def test_r1_bmu_set_locked(
        self,
        real_obligations: list[ReportingObligation],
        real_bear_artifact: dict,
    ) -> None:
        """The 14 R1 BMU numbers must match the canonical locked baseline."""
        links = _build_regulation_reporting_links(real_obligations, real_bear_artifact)
        r1_links = [
            link for link in links
            if link.reporting_obligation_id == "mt-bear-tooth-submission-r1-10day"
        ]
        # Extract BMU numbers from jurisdiction_code "MT-HD-bear-<N>"
        bmu_numbers = {int(link.jurisdiction_code.split("-")[-1]) for link in r1_links}
        expected = {100, 101, 103, 104, 110, 120, 121, 122, 123, 130, 140, 141, 150, 170}
        assert bmu_numbers == expected, (
            f"R1 BMU set mismatch. Expected {sorted(expected)}, got {sorted(bmu_numbers)}"
        )

    def test_jurisdiction_code_pattern_locked(
        self,
        real_obligations: list[ReportingObligation],
        real_bear_artifact: dict,
    ) -> None:
        """Every link's jurisdiction_code must start with 'MT-HD-bear-'."""
        links = _build_regulation_reporting_links(real_obligations, real_bear_artifact)
        bad = [
            link.jurisdiction_code for link in links
            if not link.jurisdiction_code.startswith("MT-HD-bear-")
        ]
        assert bad == [], (
            f"jurisdiction_code pattern violation; bad codes: {bad[:10]}"
        )

    def test_species_group_is_bear_not_black_bear(
        self,
        real_obligations: list[ReportingObligation],
        real_bear_artifact: dict,
    ) -> None:
        """species_group must be 'bear' (DB value), not artifact's 'black_bear'."""
        links = _build_regulation_reporting_links(real_obligations, real_bear_artifact)
        bad = [
            (link.jurisdiction_code, link.species_group)
            for link in links
            if link.species_group != "bear"
        ]
        assert bad == [], (
            f"species_group must be 'bear'; violations: {bad[:5]}"
        )

    def test_state_and_year_locked(
        self,
        real_obligations: list[ReportingObligation],
        real_bear_artifact: dict,
    ) -> None:
        """Every link must have state='US-MT' (ISO 3166-2 per DDL) and license_year=2026."""
        links = _build_regulation_reporting_links(real_obligations, real_bear_artifact)
        bad_state = [link for link in links if link.state != "US-MT"]
        bad_year = [link for link in links if link.license_year != 2026]
        assert bad_state == [], f"Links with wrong state: {bad_state[:3]}"
        assert bad_year == [], f"Links with wrong license_year: {bad_year[:3]}"

    def test_unknown_hd_region_raises(
        self, real_obligations: list[ReportingObligation]
    ) -> None:
        """A bear row with hd_region='X' must raise RuntimeError naming it."""
        artifact = {
            "rows": [
                {
                    "bmu_number": 999,
                    "hd_region": "X",
                }
            ]
        }
        with pytest.raises(RuntimeError, match=r"unknown hd_region"):
            _build_regulation_reporting_links(real_obligations, artifact)

    def test_missing_rows_key_raises(
        self, real_obligations: list[ReportingObligation]
    ) -> None:
        with pytest.raises(RuntimeError, match=r"rows"):
            _build_regulation_reporting_links(real_obligations, {})

    def test_row_entry_not_a_dict_raises_with_diagnostic(
        self,
        real_obligations: list[ReportingObligation],
        real_bear_artifact: dict,
    ) -> None:
        """A non-dict rows entry fails loud BEFORE the KeyError handler runs.

        The KeyError handler references `sorted(row.keys())` in its
        diagnostic, which itself raises AttributeError if row is a non-dict.
        The isinstance check must fire first.
        """
        # Deep-copy the artifact so we don't mutate the real fixture
        import copy
        artifact = copy.deepcopy(real_bear_artifact)
        artifact["rows"][0] = "not a dict"  # type: ignore[index]
        with pytest.raises(
            RuntimeError,
            match=r"rows\[0\] is not a dict.*got str",
        ):
            _build_regulation_reporting_links(real_obligations, artifact)

    def test_missing_expected_obligation_id_raises(
        self, real_bear_artifact: dict
    ) -> None:
        """Passing only 2 of the 3 expected obligations must raise RuntimeError."""
        all_obs = _build_reporting_obligations(real_bear_artifact)
        # Drop one obligation
        partial = all_obs[:2]
        with pytest.raises(RuntimeError, match=r"missing expected ids"):
            _build_regulation_reporting_links(partial, real_bear_artifact)

    def test_no_duplicate_composite_pks(
        self,
        real_obligations: list[ReportingObligation],
        real_bear_artifact: dict,
    ) -> None:
        """No two links should share the same composite PK."""
        links = _build_regulation_reporting_links(real_obligations, real_bear_artifact)
        pks = [
            (link.state, link.jurisdiction_code, link.species_group,
             link.license_year, link.reporting_obligation_id)
            for link in links
        ]
        assert len(set(pks)) == len(pks), (
            f"Duplicate composite PKs detected; total={len(pks)}, unique={len(set(pks))}"
        )

    def test_statewide_links_one_per_bear_row(
        self,
        real_obligations: list[ReportingObligation],
        real_bear_artifact: dict,
    ) -> None:
        """STATEWIDE obligation must have exactly one link per distinct jurisdiction_code."""
        links = _build_regulation_reporting_links(real_obligations, real_bear_artifact)
        statewide_links = [
            link for link in links
            if link.reporting_obligation_id == "mt-bear-harvest-report-48hr-statewide"
        ]
        codes = [link.jurisdiction_code for link in statewide_links]
        assert len(codes) == len(set(codes)), (
            "STATEWIDE obligation has duplicate jurisdiction_codes (double-counting)"
        )
        # Must equal the total number of bear rows (35)
        assert len(statewide_links) == 35


# ---------------------------------------------------------------------------
# TestCountGuards
# ---------------------------------------------------------------------------


class TestCountGuards:
    # reporting_obligation band: expected=3, lo=2, hi=4 (strict ±30% — floor(2.1)=2, ceil(3.9)=4)

    def test_reporting_obligation_band_passes_at_3(self) -> None:
        _assert_reporting_obligation_count_within_guard(3)  # baseline — must not raise

    def test_reporting_obligation_band_passes_at_2(self) -> None:
        _assert_reporting_obligation_count_within_guard(2)  # lower bound

    def test_reporting_obligation_band_passes_at_4(self) -> None:
        _assert_reporting_obligation_count_within_guard(4)  # upper bound

    def test_reporting_obligation_band_raises_below_2(self) -> None:
        with pytest.raises(RuntimeError, match=r"\[2, 4\]"):
            _assert_reporting_obligation_count_within_guard(1)

    def test_reporting_obligation_band_raises_above_4(self) -> None:
        with pytest.raises(RuntimeError, match=r"\[2, 4\]"):
            _assert_reporting_obligation_count_within_guard(5)

    # regulation_reporting band: expected=70, lo=49, hi=91

    def test_regulation_reporting_band_passes_at_70(self) -> None:
        _assert_regulation_reporting_count_within_guard(70)  # baseline

    def test_regulation_reporting_band_passes_at_49(self) -> None:
        _assert_regulation_reporting_count_within_guard(49)  # lower bound

    def test_regulation_reporting_band_passes_at_91(self) -> None:
        _assert_regulation_reporting_count_within_guard(91)  # upper bound

    def test_regulation_reporting_band_raises_below_49(self) -> None:
        with pytest.raises(RuntimeError, match=r"\[49, 91\]"):
            _assert_regulation_reporting_count_within_guard(48)

    def test_regulation_reporting_band_raises_above_91(self) -> None:
        with pytest.raises(RuntimeError, match=r"\[49, 91\]"):
            _assert_regulation_reporting_count_within_guard(92)


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------


class TestMain:
    def test_dry_run_exits_zero_without_db_connect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Dry-run must build all records and return 0 without calling db.connect."""
        connect_called = {"value": False}

        def _no_connect() -> object:
            connect_called["value"] = True
            raise AssertionError("db.connect must NOT be called in dry-run mode")

        monkeypatch.setattr(lro.db, "connect", _no_connect)
        exit_code = main(["--dry-run"])
        assert exit_code == 0
        assert not connect_called["value"]

    def test_count_guard_fires_pre_db_connect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard violation raises BEFORE db.connect() is called."""
        connect_called = {"value": False}

        def _no_connect() -> object:
            connect_called["value"] = True
            raise AssertionError("db.connect must NOT be called when guard fails")

        monkeypatch.setattr(lro.db, "connect", _no_connect)
        # Return empty list → 0 obligations → guard band [2, 4] violated
        monkeypatch.setattr(
            lro,
            "_build_reporting_obligations",
            lambda artifact: [],
        )

        with pytest.raises(RuntimeError):
            main([])

        assert not connect_called["value"], (
            "db.connect was called even though the count guard should have aborted first"
        )

    def test_db_failure_rolls_back(self) -> None:
        """upsert_reporting_obligation raising → rollback called, commit NOT called."""
        mock_conn, _ = _make_mock_conn()

        with (
            patch.object(lro.db, "connect", return_value=mock_conn),
            patch.object(
                lro.db,
                "upsert_reporting_obligation",
                side_effect=psycopg.OperationalError("simulated"),
            ),
            patch.object(lro.db, "write_regulation_reporting"),
        ):
            with pytest.raises(psycopg.OperationalError, match="simulated"):
                main([])

        mock_conn.rollback.assert_called_once()
        mock_conn.commit.assert_not_called()
        mock_conn.close.assert_called_once()

    def test_real_artifact_smoke_dry_run_logs_expected_counts(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Dry-run smoke: log must contain expected count strings and DRY RUN."""
        with caplog.at_level(logging.INFO):
            exit_code = main(["--dry-run"])
        assert exit_code == 0
        assert "built 3 reporting_obligation rows" in caplog.text, (
            f"Expected '3 reporting_obligation rows' in log; got:\n{caplog.text}"
        )
        assert "built 70 regulation_reporting link rows" in caplog.text, (
            f"Expected '70 regulation_reporting link rows' in log; got:\n{caplog.text}"
        )
        assert "row-count guards passed" in caplog.text, (
            f"Expected 'row-count guards passed' in log; got:\n{caplog.text}"
        )
        assert "DRY RUN" in caplog.text, (
            f"Expected 'DRY RUN' in log; got:\n{caplog.text}"
        )


# ---------------------------------------------------------------------------
# TestDispatchDictDriftGuard
# ---------------------------------------------------------------------------


class TestDispatchDictDriftGuard:
    """V1 belt-and-suspenders for the slug-encoded UPSERT semantic-drift risk.

    The ``reporting_obligation.id`` slug is hand-encoded as a string that bakes
    in kind, deadline_hours, and region_scope (e.g.,
    ``mt-bear-harvest-report-48hr-statewide``). The UPSERT in
    ``db.upsert_reporting_obligation`` updates these slug-encoded fields under
    the same id, so a future edit that changes one of those structured fields
    without correspondingly updating ``id_suffix`` would silently rewrite the
    meaning of existing rows that already have ``regulation_reporting`` links
    pointing at them.

    ``_assert_dispatch_dict_drift_free(_REPORTING_ROW_SPEC)`` fires at module
    load to catch this drift. See Q19 in docs/open-questions.md for the
    project-wide fix planned pre-M2.
    """

    def test_canonical_dispatch_dict_passes(self) -> None:
        """The 3 production entries match _derive_expected_id_suffix output.

        Module imported successfully → the guard already passed at module
        load. Re-run the guard explicitly here to lock the behavior against
        regression.
        """
        import importlib

        # importlib.reload exercises the module-load guard end-to-end and
        # establishes the "established pattern" reference; if the canonical
        # spec drifts, this test fails at reload time.
        importlib.reload(lro)
        lro._assert_dispatch_dict_drift_free(lro._REPORTING_ROW_SPEC)

    def test_drifted_id_suffix_raises_with_diagnostic(self) -> None:
        """A drifted spec entry triggers RuntimeError naming the offending key."""
        # Build a drifted copy: change R1's id_suffix without correspondingly
        # updating kind/deadline_hours/region_scope. The slug-derivation
        # function will produce the canonical "tooth-submission-r1-10day"
        # while the entry carries the drifted suffix — assertion must raise.
        drifted = dict(lro._REPORTING_ROW_SPEC)
        drifted[("R1", "tooth_submission")] = {
            **lro._REPORTING_ROW_SPEC[("R1", "tooth_submission")],
            "id_suffix": "drifted-suffix-that-does-not-match",
        }
        with pytest.raises(
            RuntimeError,
            match=r"drift detected.*R1.*tooth_submission",
        ):
            lro._assert_dispatch_dict_drift_free(drifted)

    def test_drifted_kind_raises_with_diagnostic(self) -> None:
        """Changing kind without updating id_suffix triggers the guard."""
        drifted = dict(lro._REPORTING_ROW_SPEC)
        # Same id_suffix, but kind changed → derivation produces a different
        # expected suffix than the entry's stale id_suffix.
        drifted[("STATEWIDE", "harvest_report")] = {
            **lro._REPORTING_ROW_SPEC[("STATEWIDE", "harvest_report")],
            "kind": "mandatory_check",  # was "harvest_report"
        }
        with pytest.raises(
            RuntimeError,
            match=r"drift detected.*STATEWIDE.*harvest_report",
        ):
            lro._assert_dispatch_dict_drift_free(drifted)

    def test_drifted_deadline_hours_raises_with_diagnostic(self) -> None:
        """Changing deadline_hours without updating id_suffix triggers the guard."""
        drifted = dict(lro._REPORTING_ROW_SPEC)
        # 48 → 72 changes the "48hr" token in the derived suffix to "72hr".
        drifted[("STATEWIDE", "harvest_report")] = {
            **lro._REPORTING_ROW_SPEC[("STATEWIDE", "harvest_report")],
            "deadline_hours": 72,  # was 48
        }
        with pytest.raises(RuntimeError, match=r"drift detected"):
            lro._assert_dispatch_dict_drift_free(drifted)

    def test_derive_function_rejects_unrepresentable_deadline(self) -> None:
        """deadline_hours that doesn't fit the encoding raises with diagnostic.

        Encoding: ``<= 48`` → ``"{N}hr"``; ``> 48 and % 24 == 0`` → ``"{N//24}day"``.
        A value like 60 hours is > 48 AND 60 % 24 = 12, so it's neither
        representable as hours (above the 48 threshold) nor as whole days.
        """
        with pytest.raises(
            RuntimeError,
            match=r"deadline_hours=60.*not representable",
        ):
            lro._derive_expected_id_suffix("harvest_report", 60, "STATEWIDE")

    def test_derive_function_rejects_unknown_region(self) -> None:
        """region_scope not in _REGION_SCOPE_SLUG raises with diagnostic."""
        with pytest.raises(
            RuntimeError,
            match=r"region_scope='R8'.*not in",
        ):
            lro._derive_expected_id_suffix("harvest_report", 48, "R8")

    def test_derive_function_known_kind_override_applied(self) -> None:
        """hide_skull_presentation → 'hide-skull' (the _KIND_SLUG_OVERRIDES path)."""
        assert lro._derive_expected_id_suffix(
            "hide_skull_presentation", 240, "R2-7",
        ) == "hide-skull-r2to7-10day"

    def test_derive_function_kind_with_no_override_uses_simple_replacement(self) -> None:
        """kind without an override gets _-to-- replacement only."""
        assert lro._derive_expected_id_suffix(
            "tooth_submission", 240, "R1",
        ) == "tooth-submission-r1-10day"

    def test_derive_function_statewide_suffix_positioning(self) -> None:
        """STATEWIDE goes at the end; specific regions sit between kind and deadline."""
        assert lro._derive_expected_id_suffix(
            "harvest_report", 48, "STATEWIDE",
        ) == "harvest-report-48hr-statewide"
