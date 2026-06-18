"""Unit tests for states.colorado.load_restricted_area_verbatim — pure-function, no real PDF or DB.

Covers:
- ADR-005 state-agnostic-clean guard (TestNoLibImports)
- ADR-008 no-layout=True AST regression guard (TestNoLayoutTrueRegression)
- Parser byte-equivalence and fail-loud behaviour (TestParsers)
- verbatim-map construction and key/value structure (TestBuildVerbatimMap)
- Pre-connect guard validation (TestCheckMap)
- main() dry-run and live-path integration (TestMain)
- Live PDF byte-equivalence (TestLivePdfIntegration — skipped when PDF absent)
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import states.colorado.load_restricted_area_verbatim as load_mod
from states.colorado.load_restricted_area_verbatim import (
    _AFA_GEOM_ID,
    _NPS_GEOM_IDS,
    _PDF_PATH,
    build_verbatim_map,
    main,
    parse_afa_access_text,
    parse_nps_closure_text,
    read_brochure_spans,
    _check_map,
)

# ---------------------------------------------------------------------------
# Locked verbatim spans (byte-equivalent to pdfplumber output)
# ---------------------------------------------------------------------------

_LOCKED_NPS_TEXT = (
    "National parks and monuments managed by the\n"
    "National Park Service are closed to hunting. Check\n"
    "park websites for more information."
)

_LOCKED_AFA_TEXT = (
    "AFA hunters must pay an AFA access fee and receive a man-\n"
    "datory safety orientation. All rifle deer hunting is escorted,\n"
    "and is allowed only on the days, areas and by method of take\n"
    "authorized by the AFA. Archery white-tailed deer hunting is\n"
    "allowed by limited permit only from Dec. 1-31, self-escorted\n"
    "in specific assigned areas. Call 719-333-3308 or visit usafa.\n"
    "isportsman.net for more details."
)

# ---------------------------------------------------------------------------
# Helper: loader source path
# ---------------------------------------------------------------------------


def _loader_path() -> Path:
    spec = importlib.util.find_spec("states.colorado.load_restricted_area_verbatim")
    assert spec is not None and spec.origin is not None
    return Path(spec.origin)


# ---------------------------------------------------------------------------
# Helper: make a valid 10-entry verbatim map
# ---------------------------------------------------------------------------


def _make_valid_map(nps: str = "nps-text", afa: str = "afa-text") -> dict[str, str]:
    """Build a valid 10-entry verbatim map with distinct NPS and AFA values."""
    result: dict[str, str] = {gid: nps for gid in _NPS_GEOM_IDS}
    result[_AFA_GEOM_ID] = afa
    return result


# ---------------------------------------------------------------------------
# Helper: mock db.connect context manager
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
    """Ensure load_restricted_area_verbatim.py imports no sibling state adapter (ADR-005).

    The only permitted CO→CO import is from states.colorado.load_restricted_areas
    (which supplies _V1_EXPECTED_IDS).  Any other state adapter import is forbidden.
    """

    def test_no_montana_imports(self) -> None:
        """load_restricted_area_verbatim.py must not import from states.montana."""
        source = _loader_path().read_text(encoding="utf-8")
        tree = ast.parse(source)

        forbidden_prefixes = ("states.montana", "ingestion.states.montana")

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    for prefix in forbidden_prefixes:
                        assert not alias.name.startswith(prefix), (
                            f"load_restricted_area_verbatim.py has forbidden import: {alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for prefix in forbidden_prefixes:
                    assert not module.startswith(prefix), (
                        f"load_restricted_area_verbatim.py has forbidden from-import:"
                        f" from {module}"
                    )

    def test_no_other_state_adapter_imports(self) -> None:
        """load_restricted_area_verbatim.py must not import any non-Colorado state adapter.

        CO→CO imports (states.colorado.*) are permitted; all other state adapters
        are forbidden per ADR-005 state-isolation discipline.
        """
        source = _loader_path().read_text(encoding="utf-8")
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
                        f"load_restricted_area_verbatim.py imports a non-Colorado state"
                        f" adapter: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert not _offending(module), (
                    f"load_restricted_area_verbatim.py imports a non-Colorado state"
                    f" adapter: from {module}"
                )


# ---------------------------------------------------------------------------
# TestNoLayoutTrueRegression
# ---------------------------------------------------------------------------


class TestNoLayoutTrueRegression:
    """ADR-008 byte-equivalence guard: layout=True injects synthetic spaces.

    The loader must never pass layout=True to pdfplumber (directly or via
    ingestion.lib.pdf.extract_text).  This AST walk locks that invariant.
    """

    def test_no_layout_true_kwarg_in_loader(self) -> None:
        """AST walk: no ast.Call in the loader passes a keyword layout=True."""
        source = _loader_path().read_text(encoding="utf-8")
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for kw in node.keywords:
                if kw.arg == "layout" and isinstance(kw.value, ast.Constant):
                    assert kw.value.value is not True, (
                        "load_restricted_area_verbatim.py passes layout=True to a call;"
                        " this violates ADR-008 byte-equivalence — remove the kwarg"
                    )


# ---------------------------------------------------------------------------
# TestParsers
# ---------------------------------------------------------------------------


class TestParsers:
    """Tests for parse_nps_closure_text and parse_afa_access_text."""

    # ------------------------------------------------------------------
    # NPS parser
    # ------------------------------------------------------------------

    def _nps_fixture(self) -> str:
        """Realistic right-column text containing Statewide Restrictions items 1-6."""
        return (
            "Statewide Restrictions\n"
            "1. Hunting is prohibited in state parks unless\n"
            "specifically permitted.\n"
            "2. No hunting within 50 feet of any road.\n"
            "3. Hunter orange required during rifle seasons.\n"
            "4. Trespass laws apply to all public land adjacen-\n"
            "cies; obtain landowner permission.\n"
            "5. " + _LOCKED_NPS_TEXT + "\n"
            "6. All hunters must possess valid Colorado license.\n"
        )

    def test_nps_parser_returns_byte_equivalent_span(self) -> None:
        """parse_nps_closure_text returns the locked span byte-for-byte."""
        fixture = self._nps_fixture()
        result = parse_nps_closure_text(fixture)
        assert result == _LOCKED_NPS_TEXT, (
            f"NPS span mismatch.\n  got:      {result!r}\n  expected: {_LOCKED_NPS_TEXT!r}"
        )
        # Byte-equivalence: result must be a verbatim substring of the fixture
        assert result in fixture, "parse_nps_closure_text result is not a substring of input"

    def test_nps_parser_fails_loud_when_anchor_absent(self) -> None:
        """parse_nps_closure_text raises RuntimeError when NPS anchor is absent."""
        text_without_nps = (
            "Statewide Restrictions\n"
            "1. Hunting is prohibited in state parks.\n"
            "2. No hunting within 50 feet of any road.\n"
        )
        with pytest.raises(RuntimeError) as exc_info:
            parse_nps_closure_text(text_without_nps)
        msg = str(exc_info.value)
        # Error message must mention NPS or the anchor concept
        assert "NPS" in msg or "anchor" in msg or "not found" in msg, (
            f"RuntimeError message does not mention NPS or anchor: {msg!r}"
        )

    # ------------------------------------------------------------------
    # AFA parser
    # ------------------------------------------------------------------

    def _afa_fixture(self) -> str:
        """Realistic left-column text containing the AFA access-rules block."""
        return (
            "United States Air Force Academy\n"
            + _LOCKED_AFA_TEXT
            + "\n"
            "1. Oct. 1 - Nov. 30: rifle deer season open in zone A.\n"
            "2. Dec. 1 - Dec. 31: archery whitetail by permit only.\n"
        )

    def test_afa_parser_returns_byte_equivalent_span(self) -> None:
        """parse_afa_access_text returns the locked span byte-for-byte."""
        fixture = self._afa_fixture()
        result = parse_afa_access_text(fixture)
        assert result == _LOCKED_AFA_TEXT, (
            f"AFA span mismatch.\n  got:      {result!r}\n  expected: {_LOCKED_AFA_TEXT!r}"
        )
        # Byte-equivalence: result must be a verbatim substring of the fixture
        assert result in fixture, "parse_afa_access_text result is not a substring of input"

    def test_afa_parser_fails_loud_when_anchor_absent(self) -> None:
        """parse_afa_access_text raises RuntimeError when AFA anchor is absent."""
        text_without_afa = (
            "United States Air Force Academy\n"
            "No public hunting access.\n"
        )
        with pytest.raises(RuntimeError) as exc_info:
            parse_afa_access_text(text_without_afa)
        msg = str(exc_info.value)
        assert "AFA" in msg or "anchor" in msg or "not found" in msg, (
            f"RuntimeError message does not mention AFA or anchor: {msg!r}"
        )


# ---------------------------------------------------------------------------
# TestBuildVerbatimMap
# ---------------------------------------------------------------------------


class TestBuildVerbatimMap:
    """Tests for build_verbatim_map."""

    def test_map_keys_match_v1_set(self) -> None:
        """build_verbatim_map keys must equal _V1_EXPECTED_IDS exactly (10 entries)."""
        result = build_verbatim_map("nps-sentinel", "afa-sentinel")
        assert set(result) == load_mod._V1_EXPECTED_IDS, (
            f"key mismatch: got {sorted(result)!r}"
        )
        assert len(result) == 10, f"expected 10 entries, got {len(result)}"

    def test_phrasing_case_locked_nine_nps_share_one_string_afa_distinct(self) -> None:
        """AC #485 lock: all 9 NPS ids map to the NPS sentinel; AFA id maps to distinct value.

        The 9+1 split must be structurally enforced — not just a count check.
        """
        nps_sentinel = "nps-sentinel-unique"
        afa_sentinel = "afa-sentinel-distinct"
        result = build_verbatim_map(nps_sentinel, afa_sentinel)

        # All 9 NPS ids must map to nps_sentinel (single unique value across 9)
        nps_values = {result[gid] for gid in _NPS_GEOM_IDS}
        assert nps_values == {nps_sentinel}, (
            f"NPS ids do not all map to the NPS sentinel; got distinct values: {nps_values!r}"
        )

        # AFA id must map to the distinct AFA sentinel, not the NPS sentinel
        assert result[_AFA_GEOM_ID] == afa_sentinel, (
            f"AFA id maps to {result[_AFA_GEOM_ID]!r}, expected {afa_sentinel!r}"
        )
        assert result[_AFA_GEOM_ID] != nps_sentinel, (
            "AFA value must differ from the shared NPS sentence"
        )


# ---------------------------------------------------------------------------
# TestCheckMap
# ---------------------------------------------------------------------------


class TestCheckMap:
    """Tests for _check_map pre-connect guard."""

    def test_accepts_valid_map(self) -> None:
        """A valid 10-entry map with distinct NPS/AFA values must not raise."""
        valid = _make_valid_map(nps="nps-text", afa="afa-text")
        _check_map(valid)  # must not raise

    def test_rejects_empty_value(self) -> None:
        """A map with a whitespace-only value must raise RuntimeError."""
        bad_map = _make_valid_map(nps="nps-text", afa="afa-text")
        # Replace one NPS entry with a whitespace-only value
        one_nps_id = next(iter(_NPS_GEOM_IDS))
        bad_map[one_nps_id] = "   "
        with pytest.raises(RuntimeError) as exc_info:
            _check_map(bad_map)
        assert one_nps_id in str(exc_info.value) or "empty" in str(exc_info.value).lower(), (
            f"RuntimeError does not mention the offending id or 'empty': {exc_info.value!r}"
        )

    def test_rejects_wrong_key_set_missing_key(self) -> None:
        """A map missing one required key must raise RuntimeError."""
        incomplete = _make_valid_map()
        # Remove one NPS id
        one_nps_id = next(iter(_NPS_GEOM_IDS))
        del incomplete[one_nps_id]
        assert len(incomplete) == 9
        with pytest.raises(RuntimeError):
            _check_map(incomplete)

    def test_rejects_wrong_key_set_extra_key(self) -> None:
        """A map with an unexpected extra key must raise RuntimeError."""
        extra = _make_valid_map()
        extra["CO-restricted-some-unknown-park-geom"] = "text"
        assert len(extra) == 11
        with pytest.raises(RuntimeError):
            _check_map(extra)

    def test_rejects_afa_equal_to_nps(self) -> None:
        """If the AFA row carries the NPS closure text, the 9+1 split is broken."""
        broken = _make_valid_map(nps="shared-text", afa="shared-text")
        with pytest.raises(RuntimeError):
            _check_map(broken)


# ---------------------------------------------------------------------------
# TestMain
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for main() — dry-run and live-path, all external I/O mocked."""

    def test_dry_run_skips_db(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--dry-run: returns 0 without opening a DB connection."""
        monkeypatch.setattr(
            "states.colorado.load_restricted_area_verbatim.read_brochure_spans",
            lambda *_: (_LOCKED_NPS_TEXT, _LOCKED_AFA_TEXT),
        )
        mock_connect = MagicMock()
        with patch(
            "states.colorado.load_restricted_area_verbatim.db.connect",
            mock_connect,
        ):
            result = main(["--dry-run"])

        assert result == 0
        mock_connect.assert_not_called()

    def test_live_path_updates_all_10_rows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Live path: update_geometry_verbatim called 10 times, conn.commit called once."""
        monkeypatch.setattr(
            "states.colorado.load_restricted_area_verbatim.read_brochure_spans",
            lambda *_: (_LOCKED_NPS_TEXT, _LOCKED_AFA_TEXT),
        )

        mock_conn = MagicMock()
        connect_cm = _make_connect_cm(mock_conn)

        update_calls: list[tuple[object, str, str]] = []

        def _track_update(conn: object, geom_id: str, text: str) -> None:
            update_calls.append((conn, geom_id, text))

        with (
            patch(
                "states.colorado.load_restricted_area_verbatim.db.connect",
                return_value=connect_cm,
            ),
            patch(
                "states.colorado.load_restricted_area_verbatim.db.update_geometry_verbatim",
                side_effect=_track_update,
            ),
        ):
            result = main([])

        assert result == 0
        assert len(update_calls) == 10, (
            f"expected 10 update_geometry_verbatim calls, got {len(update_calls)}"
        )
        mock_conn.commit.assert_called_once()

        # All 10 updated geometry ids must equal _V1_EXPECTED_IDS
        updated_ids = {call[1] for call in update_calls}
        assert updated_ids == load_mod._V1_EXPECTED_IDS


# ---------------------------------------------------------------------------
# TestLivePdfIntegration
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _PDF_PATH.exists(),
    reason="brochure PDF gitignored / not fetched — run fetch_pdfs.py first",
)
class TestLivePdfIntegration:
    """End-to-end byte-equivalence lock against the real CPW Big Game brochure PDF.

    Skipped in CI (PDF is gitignored); run locally after fetching the PDF.
    """

    def test_read_brochure_spans_matches_locked_values(self) -> None:
        """read_brochure_spans() output must match the locked NPS and AFA spans byte-for-byte."""
        nps, afa = read_brochure_spans()
        assert nps == _LOCKED_NPS_TEXT, (
            f"NPS span changed — brochure may have been re-extracted.\n"
            f"  got:      {nps!r}\n"
            f"  expected: {_LOCKED_NPS_TEXT!r}"
        )
        assert afa == _LOCKED_AFA_TEXT, (
            f"AFA span changed — brochure may have been re-extracted.\n"
            f"  got:      {afa!r}\n"
            f"  expected: {_LOCKED_AFA_TEXT!r}"
        )
