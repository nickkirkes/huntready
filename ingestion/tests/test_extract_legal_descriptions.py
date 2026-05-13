"""Unit tests for `states.montana.extract_legal_descriptions` — Legal Descriptions
PDF extraction (S03.5 T10).

Test philosophy:
- All unit tests are hermetic: no real Legal Descriptions PDF required. They
  drive the public helpers directly with hand-crafted inputs that mirror the
  three-column layout discovered during S03.5 planning.
- Fixtures use literal strings and small synthetic dicts only — no live-PDF
  dependency.
- ``caplog`` for log assertions (WARNING/INFO level).
- ``monkeypatch`` for module-level constant patching and function swaps.
- ``tmp_path`` for filesystem fixtures (geometry JSON, sources.yaml).
- ``TestArtifactRegression`` skips if the committed artifact is absent (e.g.,
  clean checkout before T11 runs).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import states.montana.extract_legal_descriptions as eld
from ingestion.lib.pdf import (
    ConfidenceTier,
    PageReference,
    PdfExtractionError,
)
from states.montana.extract_legal_descriptions import (
    HeadedBlock,
    LegalDescriptionsArtifact,
    _apply_continuation_merges,
    _build_artifact,
    _canonicalize_cwd_name,
    _CWD_HEADING_RE,
    _HD_HEADING_RE,
    _PORTION_HEADING_RE,
    _consolidate_cwd_blocks,
    _extract_three_column_text,
    _load_geometry_lookup,
    _match_block_to_geometry,
    _split_column_stream_into_blocks,
)

# Reuse the AST-walk helper from test_extract_dea — state-agnostic per its
# ``allowed_state`` parameter; no need to duplicate ~130 LOC.
from tests.test_extract_dea import _find_foreign_state_imports  # noqa: E402

# ---------------------------------------------------------------------------
# Shared synthetic geometry fixture helpers
# ---------------------------------------------------------------------------

_ANTELOPE_215_GEOM_ID = "MT-HD-antelope-215-geom"
_ANTELOPE_291_GEOM_ID = "MT-HD-antelope-291-geom"
_BEAR_411_GEOM_ID = "MT-HD-bear-411-geom"
_DEL_262_GEOM_ID = "MT-HD-deer-elk-lion-262-geom"
_LIBBY_CWD_GEOM_ID = "MT-CWD-zone-libby-cwd-management-zone-geom"
_KALISPELL_CWD_GEOM_ID = "MT-CWD-zone-kalispell-cwd-management-zone-geom"


def _make_synthetic_fixture(
    *,
    include_hds: bool = True,
    include_cwd: bool = True,
) -> list[dict[str, str]]:
    """Return a minimal geometry-overlays list for unit tests."""
    entries: list[dict[str, str]] = []
    if include_hds:
        entries += [
            {
                "child_geometry_id": _ANTELOPE_215_GEOM_ID,
                "child_kind": "hunting_district",
                "parent_geometry_id": "MT-STATEWIDE-geom",
                "parent_kind": "state",
            },
            {
                "child_geometry_id": _ANTELOPE_291_GEOM_ID,
                "child_kind": "hunting_district",
                "parent_geometry_id": "MT-STATEWIDE-geom",
                "parent_kind": "state",
            },
            {
                "child_geometry_id": _BEAR_411_GEOM_ID,
                "child_kind": "hunting_district",
                "parent_geometry_id": "MT-STATEWIDE-geom",
                "parent_kind": "state",
            },
            {
                "child_geometry_id": _DEL_262_GEOM_ID,
                "child_kind": "hunting_district",
                "parent_geometry_id": "MT-STATEWIDE-geom",
                "parent_kind": "state",
            },
        ]
    if include_cwd:
        entries += [
            {
                "child_geometry_id": _LIBBY_CWD_GEOM_ID,
                "child_kind": "cwd_zone",
                "parent_geometry_id": "MT-STATEWIDE-geom",
                "parent_kind": "state",
            },
            {
                "child_geometry_id": _KALISPELL_CWD_GEOM_ID,
                "child_kind": "cwd_zone",
                "parent_geometry_id": "MT-STATEWIDE-geom",
                "parent_kind": "state",
            },
        ]
    return entries


def _write_fixture(tmp_path: Path, entries: list[dict[str, str]]) -> Path:
    """Write a geometry-overlays JSON fixture to a temp file and return its path."""
    p = tmp_path / "geometry-overlays.json"
    p.write_text(json.dumps(entries), encoding="utf-8")
    return p


def _make_page_reference(page_num: int = 5) -> PageReference:
    return {
        "pdf_filename": "test.pdf",
        "page_num_1based": page_num,
        "bbox": None,
        "extracted_at": "2026-05-12T00:00:00Z",
    }


# ---------------------------------------------------------------------------
# 1. TestHeadingRegex
# ---------------------------------------------------------------------------


class TestHeadingRegex:
    """Exercise _HD_HEADING_RE, _CWD_HEADING_RE, and _PORTION_HEADING_RE."""

    def test_two_digit_hd(self) -> None:
        """2-digit HD: captures number and name."""
        text = "  21 East Deer Lodge: Those portions of Granite County lying within"
        m = _HD_HEADING_RE.search(text)
        assert m is not None, "2-digit HD heading not matched"
        assert m.group(1) == "21"
        assert m.group(2).strip() == "East Deer Lodge"

    def test_three_digit_hd(self) -> None:
        """3-digit HD: captures number and name."""
        text = "215 East Deer Lodge: Those portions of Granite County lying within"
        m = _HD_HEADING_RE.search(text)
        assert m is not None, "3-digit HD heading not matched"
        assert m.group(1) == "215"
        assert m.group(2).strip() == "East Deer Lodge"

    def test_hd_name_with_apostrophe(self) -> None:
        """HD name containing apostrophe ('O'Brien Creek') is captured."""
        text = "100 O'Brien Creek: Those portions of Lincoln County lying within"
        m = _HD_HEADING_RE.search(text)
        assert m is not None, "HD heading with apostrophe not matched"
        assert m.group(1) == "100"
        assert "O'Brien" in m.group(2)

    def test_hd_name_with_hyphen(self) -> None:
        """HD name containing hyphen ('Sun-River Wildlife') is captured."""
        text = "110 Sun-River Wildlife: That portion of Teton County"
        m = _HD_HEADING_RE.search(text)
        assert m is not None, "HD heading with hyphenated name not matched"
        assert m.group(1) == "110"
        assert "Sun-River" in m.group(2)

    def test_hd_name_with_internal_digit(self) -> None:
        """HD name containing an internal digit ('North Fork 116 Boundary') is captured."""
        text = "116 North Fork 116 Boundary: Those portions of Flathead County"
        m = _HD_HEADING_RE.search(text)
        assert m is not None, "HD heading with digit in name not matched"
        assert m.group(1) == "116"
        assert "North Fork" in m.group(2)

    def test_cwd_heading_full_name(self) -> None:
        """CWD heading with 'Zone' suffix is matched."""
        text = "Libby CWD Management Zone: Those portions of Lincoln County"
        m = _CWD_HEADING_RE.search(text)
        assert m is not None, "_CWD_HEADING_RE did not match 'Libby CWD Management Zone'"
        assert "Libby CWD Management Zone" in m.group(1)

    def test_cwd_heading_truncated_kalispell(self) -> None:
        """CWD heading without 'Zone' suffix (Kalispell line-wrap case) is matched."""
        text = "Kalispell Area CWD Management"
        m = _CWD_HEADING_RE.search(text)
        assert m is not None, (
            "_CWD_HEADING_RE did not match truncated 'Kalispell Area CWD Management'"
        )
        assert "Kalispell Area CWD Management" in m.group(1)

    def test_portion_sub_heading(self) -> None:
        """'Portion of HD NNN:' sub-heading is matched by _PORTION_HEADING_RE."""
        text = "Portion of HD 103 North Fisher:"
        m = _PORTION_HEADING_RE.search(text)
        assert m is not None, "_PORTION_HEADING_RE did not match 'Portion of HD 103'"
        assert m.group(1) == "103"

    def test_malformed_line_no_match(self) -> None:
        """A random prose line produces zero _HD_HEADING_RE matches."""
        text = "Not a heading line at all"
        assert _HD_HEADING_RE.search(text) is None


# ---------------------------------------------------------------------------
# 2. TestColumnCropping
# ---------------------------------------------------------------------------


class _FakeCroppedPage:
    """Stub for a pdfplumber-cropped page fragment."""

    def __init__(self, text: str) -> None:
        self._text = text

    def filter(self, fn: Any) -> "_FakeCroppedPage":
        # Return self; we don't actually filter in this stub.
        return self

    def extract_text(self) -> str:
        return self._text


class _FakePage:
    """Stub for a pdfplumber page with three-column text."""

    def __init__(self, height: float, col1: str, col2: str, col3: str) -> None:
        self.height = height
        self._cols = [col1, col2, col3]
        self._crop_idx = 0

    def crop(self, bbox: tuple[float, float, float, float]) -> _FakeCroppedPage:
        idx = self._crop_idx
        self._crop_idx += 1
        return _FakeCroppedPage(self._cols[idx])


class TestColumnCropping:
    """_extract_three_column_text returns a (col1, col2, col3) tuple."""

    def test_three_column_shape_and_values(self) -> None:
        """Three columns are extracted in left-to-right order."""
        page = _FakePage(800.0, "alpha text", "beta text", "gamma text")
        result = _extract_three_column_text(page)
        assert result == ("alpha text", "beta text", "gamma text"), result

    def test_empty_column_returns_empty_string(self) -> None:
        """A column returning None-equivalent text returns '' not None."""
        page = _FakePage(800.0, "", "", "")
        c1, c2, c3 = _extract_three_column_text(page)
        assert c1 == ""
        assert c2 == ""
        assert c3 == ""

    def test_three_crops_called(self) -> None:
        """crop() is called exactly three times — once per column bbox."""
        page = _FakePage(800.0, "a", "b", "c")
        _extract_three_column_text(page)
        assert page._crop_idx == 3


# ---------------------------------------------------------------------------
# 3. TestSplitColumnStream
# ---------------------------------------------------------------------------


def _hd_stream(number: int, name: str, body: str = "lying within the region.") -> str:
    """Build a minimal HD heading stream fragment."""
    return f"{number} {name}: Those portions of {body}"


def _portion_stream(number: int) -> str:
    return f"Portion of HD {number}:"


class TestSplitColumnStream:
    """_split_column_stream_into_blocks correctly splits headed blocks."""

    def test_two_hds_back_to_back(self) -> None:
        """Two consecutive HD headings produce two blocks with the right numbers."""
        stream = (
            _hd_stream(215, "East Deer Lodge", "Granite County lying within") + "\n"
            + "first body prose.\n"
            + _hd_stream(291, "West Fork", "Ravalli County lying within") + "\n"
            + "second body prose.\n"
        )
        blocks = _split_column_stream_into_blocks(stream, page_num_1based=5)
        hd_blocks = [b for b in blocks if b.kind == "hd"]
        assert len(hd_blocks) == 2, f"Expected 2 HD blocks, got: {[b.hd_number for b in hd_blocks]}"
        assert hd_blocks[0].hd_number == 215
        assert hd_blocks[1].hd_number == 291

    def test_hd_followed_by_cwd(self) -> None:
        """An HD heading followed by a CWD heading produces [hd, cwd] kinds."""
        stream = (
            _hd_stream(262, "Upper Clark Fork", "Powell County lying within") + "\n"
            + "some body text.\n"
            + "Libby CWD Management Zone: Those portions of Lincoln County\n"
            + "cwd body.\n"
        )
        blocks = _split_column_stream_into_blocks(stream, page_num_1based=19)
        kinds = [b.kind for b in blocks]
        assert "hd" in kinds
        assert "cwd" in kinds

    def test_leading_prose_before_first_heading_yields_continuation(self) -> None:
        """Prose before the first heading in the stream becomes a continuation block."""
        stream = (
            "This text continues from the prior page.\n"
            + _hd_stream(215, "East Deer Lodge", "Granite County lying within") + "\n"
        )
        blocks = _split_column_stream_into_blocks(stream, page_num_1based=6)
        assert blocks[0].kind == "continuation", (
            f"Expected first block to be 'continuation', got '{blocks[0].kind}'"
        )
        assert any(b.kind == "hd" for b in blocks)

    def test_hd_followed_by_portion(self) -> None:
        """An HD heading followed by a portion sub-heading produces [hd, portion] kinds."""
        stream = (
            _hd_stream(103, "North Fisher", "Lincoln County lying within") + "\n"
            + "body of main HD.\n"
            + _portion_stream(103) + "\n"
            + "portion body.\n"
        )
        blocks = _split_column_stream_into_blocks(stream, page_num_1based=7)
        kinds = [b.kind for b in blocks]
        assert "hd" in kinds
        assert "portion" in kinds

    def test_empty_stream_returns_empty_list(self) -> None:
        """Blank/whitespace-only stream returns []."""
        blocks = _split_column_stream_into_blocks("   \n\n  ", page_num_1based=5)
        assert blocks == []

    def test_body_captured_correctly(self) -> None:
        """The body of a block is the text between consecutive heading anchors."""
        stream = (
            _hd_stream(215, "East Deer Lodge", "Granite County lying within") + "\n"
            + "This is the description body.\n"
            + _hd_stream(291, "West Fork", "Ravalli County lying within") + "\n"
        )
        blocks = _split_column_stream_into_blocks(stream, page_num_1based=5)
        hd_blocks = [b for b in blocks if b.kind == "hd"]
        assert len(hd_blocks) >= 1
        # First block body should contain our prose but not the second heading
        assert "description body" in hd_blocks[0].body_raw


# ---------------------------------------------------------------------------
# 4. TestGeometryLookup
# ---------------------------------------------------------------------------


class TestGeometryLookup:
    """_load_geometry_lookup correctly builds lookup structures from fixture JSON."""

    def test_hd_lookup_populated(self, tmp_path: Path) -> None:
        """hd_lookup contains entries for all three V1 namespaces."""
        fixture_path = _write_fixture(tmp_path, _make_synthetic_fixture())
        hd_lookup, _cwd_lookup, _all_v1_ids = _load_geometry_lookup(fixture_path)
        assert ("antelope", 215) in hd_lookup
        assert hd_lookup[("antelope", 215)] == _ANTELOPE_215_GEOM_ID
        assert ("antelope", 291) in hd_lookup
        assert ("bear", 411) in hd_lookup
        assert ("deer-elk-lion", 262) in hd_lookup

    def test_cwd_lookup_populated(self, tmp_path: Path) -> None:
        """cwd_lookup contains entries for both Libby and Kalispell."""
        fixture_path = _write_fixture(tmp_path, _make_synthetic_fixture())
        _hd_lookup, cwd_lookup, _all_v1_ids = _load_geometry_lookup(fixture_path)
        assert "Libby CWD Management Zone" in cwd_lookup
        assert cwd_lookup["Libby CWD Management Zone"] == _LIBBY_CWD_GEOM_ID
        assert "Kalispell Area CWD Management Zone" in cwd_lookup
        assert cwd_lookup["Kalispell Area CWD Management Zone"] == _KALISPELL_CWD_GEOM_ID

    def test_all_v1_ids_union(self, tmp_path: Path) -> None:
        """all_v1_ids is the union of V1 HD IDs + CWD IDs."""
        fixture_path = _write_fixture(tmp_path, _make_synthetic_fixture())
        _hd_lookup, _cwd_lookup, all_v1_ids = _load_geometry_lookup(fixture_path)
        geom_ids = {gid for gid, _ in all_v1_ids}
        assert _ANTELOPE_215_GEOM_ID in geom_ids
        assert _LIBBY_CWD_GEOM_ID in geom_ids
        assert _KALISPELL_CWD_GEOM_ID in geom_ids

    def test_empty_fixture_raises(self, tmp_path: Path) -> None:
        """Empty fixture (no entries) raises PdfExtractionError."""
        fixture_path = _write_fixture(tmp_path, [])
        with pytest.raises(PdfExtractionError, match="empty"):
            _load_geometry_lookup(fixture_path)

    def test_missing_cwd_target_raises(self, tmp_path: Path) -> None:
        """Fixture lacking a hardcoded CWD target raises PdfExtractionError naming it."""
        # Only include HDs, no CWD entries
        entries = _make_synthetic_fixture(include_cwd=False)
        fixture_path = _write_fixture(tmp_path, entries)
        with pytest.raises(PdfExtractionError, match="CWD"):
            _load_geometry_lookup(fixture_path)

    def test_missing_hd_entries_raises(self, tmp_path: Path) -> None:
        """Fixture with only CWD entries (no HD entries) raises PdfExtractionError."""
        entries = _make_synthetic_fixture(include_hds=False)
        fixture_path = _write_fixture(tmp_path, entries)
        with pytest.raises(PdfExtractionError, match="empty"):
            _load_geometry_lookup(fixture_path)


# ---------------------------------------------------------------------------
# 5. TestCanonicalizeCwdName
# ---------------------------------------------------------------------------


class TestCanonicalizeCwdName:
    """_canonicalize_cwd_name appends 'Zone' suffix when missing."""

    def test_already_has_zone_suffix(self) -> None:
        """Name already ending in ' Zone' is returned unchanged."""
        result = _canonicalize_cwd_name("Libby CWD Management Zone")
        assert result == "Libby CWD Management Zone"

    def test_missing_zone_suffix_appended(self) -> None:
        """Kalispell name without trailing 'Zone' gets suffix appended."""
        result = _canonicalize_cwd_name("Kalispell Area CWD Management")
        assert result == "Kalispell Area CWD Management Zone"


# ---------------------------------------------------------------------------
# 6. TestMatchBlockToGeometry
# ---------------------------------------------------------------------------


def _make_hd_lookup() -> dict[tuple[str, int], str]:
    return {
        ("antelope", 215): _ANTELOPE_215_GEOM_ID,
        ("bear", 411): _BEAR_411_GEOM_ID,
        ("deer-elk-lion", 262): _DEL_262_GEOM_ID,
    }


def _make_cwd_lookup() -> dict[str, str]:
    return {
        "Libby CWD Management Zone": _LIBBY_CWD_GEOM_ID,
        "Kalispell Area CWD Management Zone": _KALISPELL_CWD_GEOM_ID,
    }


def _make_hd_block(
    hd_number: int,
    body: str = "some body.",
    page_num: int = 5,
) -> HeadedBlock:
    return HeadedBlock(
        kind="hd",
        heading_text=f"{hd_number} Test Name",
        hd_number=hd_number,
        cwd_name=None,
        body_raw=body,
        page_num_1based=page_num,
    )


def _make_cwd_block(cwd_name: str, page_num: int = 19) -> HeadedBlock:
    return HeadedBlock(
        kind="cwd",
        heading_text=cwd_name,
        hd_number=None,
        cwd_name=cwd_name,
        body_raw="cwd body prose.",
        page_num_1based=page_num,
    )


def _make_portion_block(hd_number: int = 103, page_num: int = 7) -> HeadedBlock:
    return HeadedBlock(
        kind="portion",
        heading_text=f"Portion of HD {hd_number}",
        hd_number=hd_number,
        cwd_name=None,
        body_raw="portion body prose.",
        page_num_1based=page_num,
    )


def _make_continuation_block(page_num: int = 5) -> HeadedBlock:
    return HeadedBlock(
        kind="continuation",
        heading_text="",
        hd_number=None,
        cwd_name=None,
        body_raw="continuation prose.",
        page_num_1based=page_num,
    )


class TestMatchBlockToGeometry:
    """_match_block_to_geometry returns correct matched/unmatched results."""

    def test_hd_hit(self) -> None:
        """HD block with known number → matched with geometry_id and HIGH confidence."""
        block = _make_hd_block(215)
        status, payload = _match_block_to_geometry(
            block, "antelope", _make_hd_lookup(), _make_cwd_lookup()
        )
        assert status == "matched"
        assert payload["geometry_id"] == _ANTELOPE_215_GEOM_ID
        assert payload["geometry_kind"] == "hunting_district"
        assert payload["extraction_confidence"] == ConfidenceTier.HIGH

    def test_hd_miss(self) -> None:
        """HD block with unknown number → unmatched with expected reason."""
        block = _make_hd_block(999)
        status, payload = _match_block_to_geometry(
            block, "antelope", _make_hd_lookup(), _make_cwd_lookup()
        )
        assert status == "unmatched"
        assert payload["reason"] == "no_matching_hd_in_geometry_table"

    def test_cwd_hit(self) -> None:
        """CWD block with known zone name → matched with correct geometry_id."""
        block = _make_cwd_block("Libby CWD Management Zone")
        status, payload = _match_block_to_geometry(
            block, "deer-elk-lion", _make_hd_lookup(), _make_cwd_lookup()
        )
        assert status == "matched"
        assert payload["geometry_id"] == _LIBBY_CWD_GEOM_ID
        assert payload["geometry_kind"] == "cwd_zone"

    def test_cwd_hit_via_canonicalization(self) -> None:
        """CWD block without 'Zone' suffix is matched via _canonicalize_cwd_name."""
        block = _make_cwd_block("Kalispell Area CWD Management")
        status, payload = _match_block_to_geometry(
            block, "deer-elk-lion", _make_hd_lookup(), _make_cwd_lookup()
        )
        assert status == "matched"
        assert "kalispell" in payload["geometry_id"].lower()

    def test_portion_always_unmatched(self) -> None:
        """Portion block → always unmatched with the opaque-slug reason."""
        block = _make_portion_block()
        status, payload = _match_block_to_geometry(
            block, "deer-elk-lion", _make_hd_lookup(), _make_cwd_lookup()
        )
        assert status == "unmatched"
        assert payload["reason"] == "portion_sub_heading_not_resolvable_to_opaque_slug"

    def test_continuation_block_raises(self) -> None:
        """Continuation block → PdfExtractionError (programming error guard)."""
        block = _make_continuation_block()
        with pytest.raises(PdfExtractionError, match="continuation"):
            _match_block_to_geometry(
                block, "antelope", _make_hd_lookup(), _make_cwd_lookup()
            )


# ---------------------------------------------------------------------------
# 7. TestConsolidateCwdBlocks
# ---------------------------------------------------------------------------


class TestConsolidateCwdBlocks:
    """_consolidate_cwd_blocks merges repeated CWD heading blocks."""

    def _make_cwd_tuple(
        self, cwd_name: str, body: str, page_num: int = 19
    ) -> tuple[HeadedBlock, str, PageReference]:
        block = HeadedBlock(
            kind="cwd",
            heading_text=cwd_name,
            hd_number=None,
            cwd_name=cwd_name,
            body_raw=body,
            page_num_1based=page_num,
        )
        return (block, "deer-elk-lion", _make_page_reference(page_num))

    def test_three_occurrences_merged_to_one(self) -> None:
        """Three Libby CWD blocks merge into a single block."""
        inputs = [
            self._make_cwd_tuple("Libby CWD Management Zone", "body part one."),
            self._make_cwd_tuple("Libby CWD Management Zone", "body part two."),
            self._make_cwd_tuple("Libby CWD Management Zone", "body part three."),
        ]
        result = _consolidate_cwd_blocks(inputs)
        cwd_blocks = [(b, ns, pr) for b, ns, pr in result if b.kind == "cwd"]
        assert len(cwd_blocks) == 1, f"Expected 1 CWD block, got {len(cwd_blocks)}"
        merged_body = cwd_blocks[0][0].body_raw
        assert "body part one" in merged_body
        assert "body part two" in merged_body
        assert "body part three" in merged_body

    def test_merged_body_is_concatenation_of_all(self) -> None:
        """Merged block body is all three bodies joined (in order)."""
        inputs = [
            self._make_cwd_tuple("Libby CWD Management Zone", "AAA"),
            self._make_cwd_tuple("Libby CWD Management Zone", "BBB"),
            self._make_cwd_tuple("Libby CWD Management Zone", "CCC"),
        ]
        result = _consolidate_cwd_blocks(inputs)
        merged_body = result[0][0].body_raw
        # All three fragments should appear in order in the concatenation
        idx_a = merged_body.find("AAA")
        idx_b = merged_body.find("BBB")
        idx_c = merged_body.find("CCC")
        assert idx_a < idx_b < idx_c, f"Body order wrong: {merged_body!r}"

    def test_idempotent(self) -> None:
        """Running consolidate twice yields the same result."""
        inputs = [
            self._make_cwd_tuple("Libby CWD Management Zone", "body part one."),
            self._make_cwd_tuple("Libby CWD Management Zone", "body part two."),
        ]
        once = _consolidate_cwd_blocks(inputs)
        twice = _consolidate_cwd_blocks(once)
        assert len(once) == len(twice)
        assert once[0][0].body_raw == twice[0][0].body_raw

    def test_non_cwd_blocks_pass_through(self) -> None:
        """HD and portion blocks are not affected by consolidation."""
        hd_block = (
            _make_hd_block(215, body="hd body."),
            "antelope",
            _make_page_reference(5),
        )
        cwd_block = self._make_cwd_tuple("Libby CWD Management Zone", "cwd body.")
        inputs = [hd_block, cwd_block]
        result = _consolidate_cwd_blocks(inputs)
        assert len(result) == 2
        assert result[0][0].kind == "hd"
        assert result[1][0].kind == "cwd"

    def test_different_cwd_zones_not_merged(self) -> None:
        """Libby and Kalispell blocks are NOT merged together."""
        inputs = [
            self._make_cwd_tuple("Libby CWD Management Zone", "libby body."),
            self._make_cwd_tuple("Kalispell Area CWD Management Zone", "kalispell body."),
        ]
        result = _consolidate_cwd_blocks(inputs)
        cwd_blocks = [(b, ns, pr) for b, ns, pr in result if b.kind == "cwd"]
        assert len(cwd_blocks) == 2


# ---------------------------------------------------------------------------
# 8. TestApplyContinuationMerges
# ---------------------------------------------------------------------------


class TestApplyContinuationMerges:
    """_apply_continuation_merges folds continuation blocks into prior block bodies."""

    def _make_hd_tuple(
        self, hd_number: int, body: str, page_num: int = 5
    ) -> tuple[HeadedBlock, str, PageReference]:
        block = _make_hd_block(hd_number, body=body, page_num=page_num)
        return (block, "antelope", _make_page_reference(page_num))

    def _make_continuation_tuple(
        self, body: str, page_num: int = 6
    ) -> tuple[HeadedBlock, str, PageReference]:
        block = _make_continuation_block(page_num=page_num)
        block = HeadedBlock(
            kind="continuation",
            heading_text="",
            hd_number=None,
            cwd_name=None,
            body_raw=body,
            page_num_1based=page_num,
        )
        return (block, "antelope", _make_page_reference(page_num))

    def test_continuation_appended_to_prior_hd(self) -> None:
        """Continuation block after an HD block grows that block's body."""
        hd_tuple = self._make_hd_tuple(215, "first part of description.")
        cont_tuple = self._make_continuation_tuple("continued on next column.")
        result = _apply_continuation_merges([hd_tuple, cont_tuple])
        assert len(result) == 1, "Continuation should be consumed, leaving 1 block"
        merged_body = result[0][0].body_raw
        assert "first part" in merged_body
        assert "continued on next column" in merged_body

    def test_orphan_continuation_at_index_0_is_dropped(self, caplog: Any) -> None:
        """Continuation with no prior block is dropped with a WARNING log."""
        cont_tuple = self._make_continuation_tuple("orphan prose at start of section.")
        with caplog.at_level(logging.WARNING):
            result = _apply_continuation_merges([cont_tuple])
        assert result == [], f"Orphan continuation should be dropped; got {result}"
        # ADR-001 fail-loud: dropped content surfaced at WARNING with body preview.
        assert any(
            "Dropping cross-section / orphan continuation block" in rec.message
            for rec in caplog.records
        ), f"Expected warning log; got: {[r.message for r in caplog.records]}"

    def test_cross_namespace_continuation_is_dropped_not_merged(
        self, caplog: Any
    ) -> None:
        """Continuation whose namespace differs from prior block's is dropped.

        Guards against cross-section continuation merge corruption: when section
        N+1 starts on a new page that begins with prose (a section header or
        out-of-scope bleed from section N's last page), the continuation must
        NOT be folded into section N's last block. Discovered by silent-failure
        review 2026-05-12 — without this guard, MT-HD-antelope-704 picked up
        621 chars of bison prose and MT-HD-bear-700 picked up the deer-elk-lion
        section header.
        """
        # Section N: last antelope HD
        antelope_tuple = self._make_hd_tuple(704, "antelope HD 704 body ends.", page_num=9)
        # Section N+1: page 14 starts with bear-namespace continuation prose
        cont_block = HeadedBlock(
            kind="continuation",
            heading_text="",
            hd_number=None,
            cwd_name=None,
            body_raw="THIS IS BEAR-NAMESPACE PROSE THAT MUST NOT MERGE INTO ANTELOPE 704",
            page_num_1based=14,
        )
        cont_tuple = (cont_block, "bear", _make_page_reference(14))
        # Section N+1: first bear HD on page 14
        bear_tuple = self._make_hd_tuple(100, "bear HD 100 body.", page_num=14)
        # Coerce the bear tuple's namespace from "antelope" (helper default) to "bear"
        bear_block, _, bear_pref = bear_tuple
        bear_tuple = (bear_block, "bear", bear_pref)

        with caplog.at_level(logging.WARNING):
            result = _apply_continuation_merges([antelope_tuple, cont_tuple, bear_tuple])

        # Antelope body untouched
        antelope_result = next(b for b, _, _ in result if b.hd_number == 704)
        assert "BEAR-NAMESPACE PROSE" not in antelope_result.body_raw, (
            "Cross-section continuation must NOT leak into prior namespace's block; "
            f"got body_raw={antelope_result.body_raw!r}"
        )
        assert antelope_result.body_raw == "antelope HD 704 body ends."

        # Bear body untouched (continuation was dropped, not prepended to bear 100)
        bear_result = next(b for b, _, _ in result if b.hd_number == 100)
        assert "BEAR-NAMESPACE PROSE" not in bear_result.body_raw

        # WARNING log naming the cross-section drop emitted
        assert any(
            "Dropping cross-section / orphan continuation block" in rec.message
            and "this_ns=bear" in rec.message
            and "prior_ns=antelope" in rec.message
            for rec in caplog.records
        ), f"Expected cross-section warning; got: {[r.message for r in caplog.records]}"

    def test_no_continuation_blocks_in_output(self) -> None:
        """Output contains no kind='continuation' entries."""
        inputs = [
            self._make_hd_tuple(215, "hd body."),
            self._make_continuation_tuple("extra text."),
            self._make_hd_tuple(291, "second hd body."),
        ]
        result = _apply_continuation_merges(inputs)
        kinds = [b.kind for b, _, _ in result]
        assert "continuation" not in kinds, f"Continuation still present: {kinds}"

    def test_multiple_continuations_each_appended(self) -> None:
        """Multiple consecutive continuation blocks are all folded into the prior HD."""
        hd_tuple = self._make_hd_tuple(215, "part one.")
        cont1 = self._make_continuation_tuple("part two.", page_num=6)
        cont2 = self._make_continuation_tuple("part three.", page_num=7)
        result = _apply_continuation_merges([hd_tuple, cont1, cont2])
        assert len(result) == 1
        merged = result[0][0].body_raw
        assert "part one" in merged
        assert "part two" in merged
        assert "part three" in merged


# ---------------------------------------------------------------------------
# 9. TestBuildArtifact
# ---------------------------------------------------------------------------

_FAKE_EXTRACTED_AT = "2026-05-12T00:00:00Z"


def _make_merged_blocks_with_one_matched_one_portion(
    hd_lookup: dict[tuple[str, int], str],
    cwd_lookup: dict[str, str],
) -> tuple[list[tuple[HeadedBlock, str, PageReference]], list[tuple[str, str]]]:
    """Build a synthetic merged-blocks list: 1 matched HD + 1 unmatched portion.

    The HD 215 antelope block will match; the portion block will not.
    Also returns a minimal all_v1_ids list that includes 215 + one
    extra HD (262) that has no block → lands in unlinked.
    """
    hd_block = _make_hd_block(215, body="Beginning at the junction of US-89.")
    portion_block = _make_portion_block(103)
    merged_blocks: list[tuple[HeadedBlock, str, PageReference]] = [
        (hd_block, "antelope", _make_page_reference(5)),
        (portion_block, "deer-elk-lion", _make_page_reference(20)),
    ]
    # all_v1_ids: 215 (will be matched) + 262 (will be unlinked)
    all_v1_ids: list[tuple[str, str]] = [
        (_ANTELOPE_215_GEOM_ID, "hunting_district"),
        (_DEL_262_GEOM_ID, "hunting_district"),
    ]
    return merged_blocks, all_v1_ids


class TestBuildArtifact:
    """_build_artifact produces correct matched/unmatched/unlinked arrays."""

    def test_three_arrays_populated(self) -> None:
        """Artifact has entries in all three arrays given the synthetic input."""
        hd_lookup = _make_hd_lookup()
        cwd_lookup = _make_cwd_lookup()
        merged_blocks, all_v1_ids = _make_merged_blocks_with_one_matched_one_portion(
            hd_lookup, cwd_lookup
        )
        artifact = _build_artifact(
            merged_blocks, _FAKE_EXTRACTED_AT, hd_lookup, cwd_lookup, all_v1_ids
        )
        assert len(artifact["matched"]) == 1, artifact["matched"]
        assert len(artifact["unmatched"]) == 1, artifact["unmatched"]
        assert len(artifact["unlinked"]) == 1, artifact["unlinked"]

    def test_source_id_matches_citation_id(self) -> None:
        """artifact['source_id'] is the module-level _CITATION_ID constant."""
        hd_lookup = _make_hd_lookup()
        cwd_lookup = _make_cwd_lookup()
        merged_blocks, all_v1_ids = _make_merged_blocks_with_one_matched_one_portion(
            hd_lookup, cwd_lookup
        )
        artifact = _build_artifact(
            merged_blocks, _FAKE_EXTRACTED_AT, hd_lookup, cwd_lookup, all_v1_ids
        )
        assert artifact["source_id"] == eld._CITATION_ID

    def test_matched_geometry_id_correct(self) -> None:
        """The matched entry has the expected geometry_id."""
        hd_lookup = _make_hd_lookup()
        cwd_lookup = _make_cwd_lookup()
        merged_blocks, all_v1_ids = _make_merged_blocks_with_one_matched_one_portion(
            hd_lookup, cwd_lookup
        )
        artifact = _build_artifact(
            merged_blocks, _FAKE_EXTRACTED_AT, hd_lookup, cwd_lookup, all_v1_ids
        )
        matched_ids = [e["geometry_id"] for e in artifact["matched"]]
        assert _ANTELOPE_215_GEOM_ID in matched_ids

    def test_whitespace_collapse_applied(self) -> None:
        """Cleanup Rule A: body with newlines and tabs collapses to single spaces.

        This is the named test referenced in the module docstring's Rule A
        ('Locked by test TestBuildArtifact::test_whitespace_collapse_applied').
        """
        hd_lookup = _make_hd_lookup()
        cwd_lookup = _make_cwd_lookup()
        raw_body = "line1\n\n   line2\t\ttabbed\n  "
        block = HeadedBlock(
            kind="hd",
            heading_text="215 East Deer Lodge",
            hd_number=215,
            cwd_name=None,
            body_raw=raw_body,
            page_num_1based=5,
        )
        merged_blocks: list[tuple[HeadedBlock, str, PageReference]] = [
            (block, "antelope", _make_page_reference(5)),
        ]
        all_v1_ids: list[tuple[str, str]] = [(_ANTELOPE_215_GEOM_ID, "hunting_district")]
        artifact = _build_artifact(
            merged_blocks, _FAKE_EXTRACTED_AT, hd_lookup, cwd_lookup, all_v1_ids
        )
        assert len(artifact["matched"]) == 1
        vd = artifact["matched"][0]["verbatim_description"]
        assert vd == "line1 line2 tabbed", (
            f"Expected whitespace-collapsed string; got: {vd!r}"
        )

    def test_heading_text_not_in_body(self) -> None:
        """Cleanup Rule B: heading text is NOT part of verbatim_description.

        This is the named test referenced in the module docstring's Rule B
        ('Locked by test TestBuildArtifact::test_heading_text_not_in_body').
        The regex match starts body text AFTER the heading, so the heading
        number and name do not bleed into the extracted body.
        """
        # Simulate what the splitter produces: body_raw starts after the heading
        # keyword phrase, so the heading text is not in body_raw at all.
        hd_lookup = _make_hd_lookup()
        cwd_lookup = _make_cwd_lookup()
        body_raw = "the junction of US-89 and MT-200."
        block = HeadedBlock(
            kind="hd",
            heading_text="215 East Deer Lodge",
            hd_number=215,
            cwd_name=None,
            body_raw=body_raw,
            page_num_1based=5,
        )
        merged_blocks: list[tuple[HeadedBlock, str, PageReference]] = [
            (block, "antelope", _make_page_reference(5)),
        ]
        all_v1_ids: list[tuple[str, str]] = [(_ANTELOPE_215_GEOM_ID, "hunting_district")]
        artifact = _build_artifact(
            merged_blocks, _FAKE_EXTRACTED_AT, hd_lookup, cwd_lookup, all_v1_ids
        )
        vd = artifact["matched"][0]["verbatim_description"]
        # Heading number and name must not appear in the extracted body
        assert "215" not in vd, f"HD number leaked into verbatim_description: {vd!r}"
        assert "East Deer Lodge" not in vd, (
            f"HD name leaked into verbatim_description: {vd!r}"
        )

    def test_sort_order_matched(self) -> None:
        """matched is sorted by (geometry_kind, geometry_id)."""
        hd_lookup: dict[tuple[str, int], str] = {
            ("antelope", 215): _ANTELOPE_215_GEOM_ID,
            ("deer-elk-lion", 262): _DEL_262_GEOM_ID,
        }
        cwd_lookup = _make_cwd_lookup()
        block_a = _make_hd_block(215, "body a.", page_num=5)
        block_b = _make_hd_block(262, "body b.", page_num=20)
        # Supply b first, then a — artifact should sort them
        merged_blocks: list[tuple[HeadedBlock, str, PageReference]] = [
            (block_b, "deer-elk-lion", _make_page_reference(20)),
            (block_a, "antelope", _make_page_reference(5)),
        ]
        all_v1_ids: list[tuple[str, str]] = [
            (_ANTELOPE_215_GEOM_ID, "hunting_district"),
            (_DEL_262_GEOM_ID, "hunting_district"),
        ]
        artifact = _build_artifact(
            merged_blocks, _FAKE_EXTRACTED_AT, hd_lookup, cwd_lookup, all_v1_ids
        )
        ids = [e["geometry_id"] for e in artifact["matched"]]
        assert ids == sorted(ids), f"matched not sorted by geometry_id: {ids}"

    def test_sort_order_unlinked(self) -> None:
        """unlinked is sorted by (geometry_kind, geometry_id)."""
        hd_lookup = _make_hd_lookup()
        cwd_lookup = _make_cwd_lookup()
        # No blocks → everything is unlinked
        all_v1_ids: list[tuple[str, str]] = [
            (_DEL_262_GEOM_ID, "hunting_district"),
            (_ANTELOPE_215_GEOM_ID, "hunting_district"),
        ]
        artifact = _build_artifact(
            [], _FAKE_EXTRACTED_AT, hd_lookup, cwd_lookup, all_v1_ids
        )
        ids = [e["geometry_id"] for e in artifact["unlinked"]]
        assert ids == sorted(ids), f"unlinked not sorted: {ids}"


# ---------------------------------------------------------------------------
# 10. TestMainExitCodes
# ---------------------------------------------------------------------------

def _make_artifact_with_counts(
    matched_count: int,
    regression_unmatched_count: int,
    portion_unmatched_count: int = 0,
) -> LegalDescriptionsArtifact:
    """Construct a synthetic artifact with the requested match counts."""
    matched = [
        {
            "geometry_id": f"MT-HD-antelope-{i}-geom",
            "geometry_kind": "hunting_district",
            "verbatim_description": "some description",
            "page_reference": _make_page_reference(5),
            "extraction_confidence": "high",
        }
        for i in range(matched_count)
    ]
    # Regression unmatched = HD/CWD parse failures (count toward threshold)
    unmatched_regression = [
        {
            "heading_text": f"Unknown HD {i}",
            "page_reference": _make_page_reference(5),
            "reason": "no_matching_hd_in_geometry_table",
        }
        for i in range(regression_unmatched_count)
    ]
    # Portion unmatched = by-design, excluded from threshold
    unmatched_portion = [
        {
            "heading_text": f"Portion of HD {i}",
            "page_reference": _make_page_reference(7),
            "reason": "portion_sub_heading_not_resolvable_to_opaque_slug",
        }
        for i in range(portion_unmatched_count)
    ]
    return {  # type: ignore[return-value]
        "source_id": "mt-fwp-legal-descriptions-2026-2027",
        "extracted_at": _FAKE_EXTRACTED_AT,
        "matched": matched,  # type: ignore[typeddict-item]
        "unmatched": unmatched_regression + unmatched_portion,  # type: ignore[typeddict-item]
        "unlinked": [],
    }


class TestMainExitCodes:
    """main() threshold logic: 0%, 9%, and 15% regression-unmatched scenarios."""

    def _patch_main_for_artifact(
        self,
        monkeypatch: Any,
        artifact: LegalDescriptionsArtifact,
    ) -> None:
        """Monkeypatch the pipeline so main() uses the supplied synthetic artifact."""
        # Stub out PDF opening and the full extraction pipeline
        fake_pdf_ctx = MagicMock()
        fake_pdf_ctx.__enter__ = MagicMock(return_value=MagicMock())
        fake_pdf_ctx.__exit__ = MagicMock(return_value=False)
        monkeypatch.setattr(eld, "open_pdf", lambda *a, **kw: fake_pdf_ctx)
        monkeypatch.setattr(eld, "_walk_v1_pages", lambda *a, **kw: iter([]))
        monkeypatch.setattr(eld, "_consolidate_cwd_blocks", lambda blocks: blocks)
        monkeypatch.setattr(eld, "_apply_continuation_merges", lambda blocks: blocks)
        monkeypatch.setattr(eld, "_build_artifact", lambda *a, **kw: artifact)
        # Stub out file-based inputs (citation, manifest, geometry)
        monkeypatch.setattr(
            eld,
            "_load_citation_from_sources_yaml",
            lambda citation_id: {
                "id": citation_id,
                "agency": "MT FWP",
                "title": "Test",
                "url": "https://example.com",
                "publication_date": "2026-02-03",
                "document_type": "annual_regulations",
            },
        )
        monkeypatch.setattr(
            eld,
            "_load_extracted_at_from_manifest",
            lambda pdf_path: _FAKE_EXTRACTED_AT,
        )
        monkeypatch.setattr(
            eld,
            "_load_geometry_lookup",
            lambda fixture_path: (_make_hd_lookup(), _make_cwd_lookup(), []),
        )
        # Stub out the JSON writer so no filesystem writes happen
        monkeypatch.setattr(eld, "_write_deterministic_json", lambda path, payload: None)

    def test_zero_unmatched_returns_zero(self, monkeypatch: Any, tmp_path: Path) -> None:
        """0 regression-unmatched out of 100 matched → main returns 0."""
        artifact = _make_artifact_with_counts(
            matched_count=100,
            regression_unmatched_count=0,
        )
        self._patch_main_for_artifact(monkeypatch, artifact)
        fake_pdf = tmp_path / "fake.pdf"
        fake_pdf.write_bytes(b"PDF-stub")
        exit_code = eld.main(["--pdf", str(fake_pdf)])
        assert exit_code == 0

    def test_nine_percent_below_threshold_returns_zero_with_warn(
        self, monkeypatch: Any, tmp_path: Path, caplog: Any
    ) -> None:
        """9 regression-unmatched out of 109 total → exit 0 with WARN log."""
        artifact = _make_artifact_with_counts(
            matched_count=100,
            regression_unmatched_count=9,
        )
        self._patch_main_for_artifact(monkeypatch, artifact)
        fake_pdf = tmp_path / "fake.pdf"
        fake_pdf.write_bytes(b"PDF-stub")
        with caplog.at_level(logging.WARNING):
            exit_code = eld.main(["--pdf", str(fake_pdf)])
        assert exit_code == 0
        # Should log a warning about the below-threshold unmatched count
        warning_messages = [
            r.message for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert any("9" in msg or "Regression-unmatched" in msg or "unmatched" in msg.lower()
                   for msg in warning_messages), (
            f"Expected WARN log for 9 unmatched; got: {warning_messages}"
        )

    def test_fifteen_percent_above_threshold_raises(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """15 regression-unmatched out of 115 total → PdfExtractionError raised."""
        artifact = _make_artifact_with_counts(
            matched_count=100,
            regression_unmatched_count=15,
        )
        self._patch_main_for_artifact(monkeypatch, artifact)
        fake_pdf = tmp_path / "fake.pdf"
        fake_pdf.write_bytes(b"PDF-stub")
        with pytest.raises(PdfExtractionError, match="10%"):
            eld.main(["--pdf", str(fake_pdf)])

    def test_portion_only_unmatched_does_not_count_toward_threshold(
        self, monkeypatch: Any, tmp_path: Path
    ) -> None:
        """100 portion unmatched + 100 matched → exit 0 (portions excluded)."""
        artifact = _make_artifact_with_counts(
            matched_count=100,
            regression_unmatched_count=0,
            portion_unmatched_count=100,
        )
        self._patch_main_for_artifact(monkeypatch, artifact)
        fake_pdf = tmp_path / "fake.pdf"
        fake_pdf.write_bytes(b"PDF-stub")
        exit_code = eld.main(["--pdf", str(fake_pdf)])
        assert exit_code == 0


# ---------------------------------------------------------------------------
# 11. TestArtifactRegression
# ---------------------------------------------------------------------------

_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "states"
    / "montana"
    / "extracted"
    / "legal-descriptions-2026.json"
)


class TestArtifactRegression:
    """Load the committed artifact and assert end-to-end correctness.

    Skips if the artifact file doesn't exist yet (before T11 runs).
    """

    def _load_artifact(self) -> LegalDescriptionsArtifact:
        if not _ARTIFACT_PATH.exists():
            pytest.skip(
                f"Artifact not found at {_ARTIFACT_PATH} — run extract_legal_descriptions.py "
                "first (T11) to generate it."
            )
        with _ARTIFACT_PATH.open(encoding="utf-8") as fh:
            return json.load(fh)

    def test_at_least_100_matched(self) -> None:
        """Artifact has at least 100 matched entries (sanity: V1 scope has 237 IDs)."""
        artifact = self._load_artifact()
        count = len(artifact["matched"])
        assert count >= 100, f"Only {count} matched entries found — expected ≥100"

    def test_libby_cwd_matched(self) -> None:
        """Libby CWD geometry_id is present in matched."""
        artifact = self._load_artifact()
        matched_ids = {e["geometry_id"] for e in artifact["matched"]}
        assert _LIBBY_CWD_GEOM_ID in matched_ids, (
            f"{_LIBBY_CWD_GEOM_ID} not found in matched. Present: "
            + repr(sorted(gid for gid in matched_ids if "cwd" in gid.lower()))
        )

    def test_kalispell_cwd_matched(self) -> None:
        """Kalispell CWD geometry_id is present in matched."""
        artifact = self._load_artifact()
        matched_ids = {e["geometry_id"] for e in artifact["matched"]}
        assert _KALISPELL_CWD_GEOM_ID in matched_ids, (
            f"{_KALISPELL_CWD_GEOM_ID} not found in matched."
        )

    def test_regression_unmatched_rate_below_10_percent(self) -> None:
        """Regression-unmatched rate (excluding portion sub-headings) is < 10%."""
        artifact = self._load_artifact()
        regression_unmatched = [
            u for u in artifact["unmatched"]
            if u["reason"] != "portion_sub_heading_not_resolvable_to_opaque_slug"
        ]
        matched_count = len(artifact["matched"])
        regression_count = len(regression_unmatched)
        total = matched_count + regression_count
        assert total > 0, "No matched or regression-unmatched entries — artifact empty?"
        rate = regression_count / total
        assert rate < 0.10, (
            f"Regression-unmatched rate {rate:.1%} exceeds 10% "
            f"({regression_count}/{total})"
        )

    def test_all_matched_have_non_empty_description(self) -> None:
        """Every matched entry has a non-empty verbatim_description.

        Guards against a silent parser failure that produces empty bodies —
        the artifact would pass the count/coverage tests but S03.6 would
        write `geometry.legal_description = ''` for affected rows. ADR-008
        forbids empty verbatim text where source content exists.
        """
        artifact = self._load_artifact()
        empty = [
            e["geometry_id"]
            for e in artifact["matched"]
            if not e.get("verbatim_description", "").strip()
        ]
        assert not empty, (
            f"Matched entries with empty verbatim_description: {empty}"
        )

    def test_no_cross_namespace_bleed_in_verbatim_descriptions(self) -> None:
        """No matched entry's body contains a section-header from another species namespace.

        Guards against the cross-section continuation merge corruption found
        by S03.5 silent-failure review 2026-05-12. Section headers from
        adjacent sections must NOT appear in any HD's verbatim_description.
        """
        artifact = self._load_artifact()
        # The literal section-header strings that appeared in the corrupted
        # 2026-05-12 pre-fix artifact (page-14 bear start + page-19 deer-elk-lion start).
        FOREIGN_HEADERS = (
            "Black Bear Management Unit",
            "Deer and Elk Hunting Districts",
        )
        violations = []
        for entry in artifact["matched"]:
            body = entry.get("verbatim_description", "")
            for header in FOREIGN_HEADERS:
                if header in body:
                    violations.append((entry["geometry_id"], header))
        assert not violations, (
            f"Cross-namespace section headers leaked into matched bodies: {violations}"
        )


# ---------------------------------------------------------------------------
# 12. TestNoForeignStateAdapterImports
# ---------------------------------------------------------------------------

class TestNoForeignStateAdapterImports:
    """AST-walk guard: extract_legal_descriptions.py must not import from non-montana
    state adapters, and must not import from ingestion.lib.db (single-writer contract).

    Rules per ADR-005 (adapter isolation) and S03.5 spec line 487
    (single-writer contract — S03.5 emits JSON only; S03.6 writes to DB):
      - Montana adapter may import from ``states.montana.*`` or ``ingestion.lib.*``,
        but NEVER from ``states.<other_state>.*`` or
        ``ingestion.states.<other_state>.*``.
      - extract_legal_descriptions.py must NOT import from ``ingestion.lib.db``
        (no database writes in S03.5).
    """

    _ALLOWED_STATE: str = "montana"

    def test_no_foreign_state_adapter_imports(self) -> None:
        """extract_legal_descriptions.py itself is clean of foreign state imports."""
        source_path = Path(eld.__file__)  # type: ignore[arg-type]
        source = source_path.read_text(encoding="utf-8")
        violations = _find_foreign_state_imports(source, self._ALLOWED_STATE)
        assert not violations, (
            "extract_legal_descriptions.py contains foreign state adapter imports:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_guard_catches_foreign_state_import(self) -> None:
        """Counter-example: a synthetic foreign import IS detected."""
        violations = _find_foreign_state_imports(
            "from ingestion.states.colorado import load_hds", self._ALLOWED_STATE
        )
        assert any(
            "from ingestion.states.colorado" in v for v in violations
        ), f"AST guard failed to catch foreign import: {violations}"

    def test_no_foreign_state_substrings_in_source(self) -> None:
        """Broad-scan guard: no 'states.colorado/wyoming/utah' substring appears."""
        source_path = Path(eld.__file__)  # type: ignore[arg-type]
        source = source_path.read_text(encoding="utf-8")
        for foreign in ("states.colorado", "states.wyoming", "states.utah"):
            assert foreign not in source, (
                f"Foreign state substring '{foreign}' found in "
                f"extract_legal_descriptions.py — possible false-negative import"
            )

    def test_no_db_imports(self) -> None:
        """extract_legal_descriptions.py has no ingestion.lib.db imports.

        Per S03.5 spec line 487 single-writer contract: S03.5 produces JSON
        only. No database writes. S03.6 reads the artifact and writes
        geometry.legal_description. DB imports in S03.5 would violate this.
        """
        source_path = Path(eld.__file__)  # type: ignore[arg-type]
        source = source_path.read_text(encoding="utf-8")
        assert "from ingestion.lib.db" not in source, (
            "extract_legal_descriptions.py imports from ingestion.lib.db — "
            "violates S03.5 single-writer contract (spec line 487)"
        )
        assert "import ingestion.lib.db" not in source, (
            "extract_legal_descriptions.py imports ingestion.lib.db — "
            "violates S03.5 single-writer contract (spec line 487)"
        )

    def test_guard_allows_montana_imports(self) -> None:
        """Sanity: Montana-internal imports and ingestion.lib are not flagged."""
        clean = "\n".join(
            [
                "from states.montana import fetch_pdfs",
                "from ingestion.states.montana import fetch_pdfs",
                "from ingestion.lib.pdf import open_pdf",
                "import re",
            ]
        )
        violations = _find_foreign_state_imports(clean, self._ALLOWED_STATE)
        assert violations == [], violations
