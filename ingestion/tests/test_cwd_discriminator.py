"""Unit tests for states.montana.cwd_discriminator.is_cwd_feature — pure-function, no I/O."""

from __future__ import annotations

from typing import Any

from states.montana.cwd_discriminator import is_cwd_feature

# ---------------------------------------------------------------------------
# TestIsCwdFeature
# ---------------------------------------------------------------------------


class TestIsCwdFeature:
    # ------------------------------------------------------------------
    # Cases that must return False
    # ------------------------------------------------------------------

    def test_empty_dict_returns_false(self) -> None:
        assert is_cwd_feature({}) is False

    def test_all_fields_none_returns_false(self) -> None:
        assert is_cwd_feature({"COMMENTS": None, "PORTIONNAME": None, "REG": None}) is False

    def test_all_fields_populated_no_match_returns_false(self) -> None:
        props: dict[str, Any] = {
            "COMMENTS": "Archery only in October",
            "PORTIONNAME": "North Fork District",
            "REG": "Either-sex season",
        }
        assert is_cwd_feature(props) is False

    def test_portionname_chronic_only_no_wasting_returns_false(self) -> None:
        # "Chronic" alone must not trigger the PORTIONNAME branch
        assert is_cwd_feature({"PORTIONNAME": "Chronic Disease Unit"}) is False

    def test_portionname_cwd_alone_returns_false(self) -> None:
        # PORTIONNAME branch only matches "chronic wasting" — not "CWD"
        assert is_cwd_feature({"PORTIONNAME": "CWD Management Area"}) is False

    def test_portionname_cwd_with_empty_comments_and_reg_returns_false(self) -> None:
        # Locks in the intentional asymmetry: PORTIONNAME containing "CWD"
        # (not "chronic wasting") + empty COMMENTS + empty REG must NOT match.
        # The spec is COMMENTS ILIKE '%CWD%' OR PORTIONNAME ILIKE '%chronic wasting%' OR REG ILIKE '%CWD%'
        # — PORTIONNAME's branch is deliberately narrower than COMMENTS/REG.
        assert is_cwd_feature({"PORTIONNAME": "CWD Only Area", "COMMENTS": "", "REG": ""}) is False

    def test_whitespace_only_fields_returns_false(self) -> None:
        assert is_cwd_feature({"COMMENTS": "   ", "PORTIONNAME": "   ", "REG": "   "}) is False

    # ------------------------------------------------------------------
    # Cases that must return True — COMMENTS branch
    # ------------------------------------------------------------------

    def test_comments_uppercase_cwd_returns_true(self) -> None:
        assert is_cwd_feature({"COMMENTS": "CWD Management Zone"}) is True

    def test_comments_lowercase_cwd_returns_true(self) -> None:
        # Case-insensitive
        assert is_cwd_feature({"COMMENTS": "cwd management zone"}) is True

    def test_comments_cwd_embedded_in_word_returns_true(self) -> None:
        # Substring match — mirrors SQL ILIKE '%CWD%'
        assert is_cwd_feature({"COMMENTS": "NCWDX special restriction"}) is True

    def test_comments_empty_reg_cwd_returns_true(self) -> None:
        # COMMENTS empty, REG has match
        assert is_cwd_feature({"COMMENTS": "", "REG": "cwd"}) is True

    # ------------------------------------------------------------------
    # Cases that must return True — PORTIONNAME branch
    # ------------------------------------------------------------------

    def test_portionname_chronic_wasting_disease_returns_true(self) -> None:
        assert is_cwd_feature({"PORTIONNAME": "Chronic Wasting Disease Zone"}) is True

    def test_portionname_lowercase_chronic_wasting_returns_true(self) -> None:
        assert is_cwd_feature({"PORTIONNAME": "chronic wasting management"}) is True

    # ------------------------------------------------------------------
    # Cases that must return True — REG branch
    # ------------------------------------------------------------------

    def test_reg_uppercase_cwd_returns_true(self) -> None:
        assert is_cwd_feature({"REG": "CWD restrictions apply"}) is True

    def test_reg_lowercase_cwd_returns_true(self) -> None:
        assert is_cwd_feature({"REG": "see cwd zone rules"}) is True

    # ------------------------------------------------------------------
    # Type coercion — non-string values must not raise
    # ------------------------------------------------------------------

    def test_integer_field_value_does_not_raise(self) -> None:
        # Malformed feature with int in COMMENTS — coerce to str then test
        props: dict[str, Any] = {"COMMENTS": 12345, "PORTIONNAME": 0, "REG": 99}
        assert is_cwd_feature(props) is False

    def test_integer_cwd_value_does_not_match(self) -> None:
        # Integers that happen to stringify without "CWD"
        assert is_cwd_feature({"COMMENTS": 0}) is False
