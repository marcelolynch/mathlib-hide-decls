#!/usr/bin/env python3
"""Unit tests for policy.parse_attrs — the centralized attribute parser.

Tests cover same-line and preceding-line attribute scanning, edge cases like
multi-token attributes with parens, and proper stop conditions.
"""
import sys
from pathlib import Path

# Add pipeline/src to path so we can import policy
SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
import policy


def test_same_line_single():
    """@[simp] def X — same-line, single attribute."""
    lines = ["@[simp] def foo"]
    result = policy.parse_attrs(lines, 0, "def")
    assert result == ["simp"], f"Expected ['simp'], got {result}"


def test_same_line_multiple():
    """@[simp, norm_cast] lemma X — same-line, multiple attributes."""
    lines = ["@[simp, norm_cast] lemma bar"]
    result = policy.parse_attrs(lines, 0, "lemma")
    assert result == ["simp", "norm_cast"], f"Expected ['simp', 'norm_cast'], got {result}"


def test_preceding_line_single():
    """@[simp]\nlemma baz — preceding line, single attribute."""
    lines = ["@[simp]", "lemma baz"]
    result = policy.parse_attrs(lines, 1, "lemma")
    assert result == ["simp"], f"Expected ['simp'], got {result}"


def test_preceding_line_with_docstring():
    """/-- doc --/\n@[simp]\ntheorem qux — preceding line through doc comment."""
    lines = ["/-- doc --/", "@[simp]", "theorem qux"]
    result = policy.parse_attrs(lines, 2, "theorem")
    assert result == ["simp"], f"Expected ['simp'], got {result}"


def test_multiple_preceding_lines():
    """@[simp]\n@[deprecated]\nlemma X — multiple preceding attribute lines."""
    lines = ["@[simp]", "@[deprecated]", "lemma multi_attr"]
    result = policy.parse_attrs(lines, 2, "lemma")
    # Both attributes should be found
    assert "simp" in result and "deprecated" in result, \
        f"Expected both simp and deprecated in {result}"


def test_multi_token_attr_with_parens():
    """@[deprecated foo (since := "...")] lemma X — multi-token attr with parens."""
    lines = ['@[deprecated foo (since := "v3.0")] lemma old']
    result = policy.parse_attrs(lines, 0, "lemma")
    assert "deprecated" in result, f"Expected 'deprecated' in {result}"
    # We extract tokens, so we get the first identifier before parens
    # 'deprecated' and 'foo' should both be extracted


def test_noncomputable_modifier():
    """@[simp] noncomputable def X — modifier between attr and keyword."""
    lines = ["@[simp] noncomputable def uncomputable"]
    result = policy.parse_attrs(lines, 0, "def")
    assert result == ["simp"], f"Expected ['simp'], got {result}"


def test_already_private():
    """@[simp]\nprivate lemma X — already private should still report attrs."""
    lines = ["@[simp]", "private lemma already_hidden"]
    result = policy.parse_attrs(lines, 1, "lemma")
    assert result == ["simp"], f"Expected ['simp'], got {result}"


def test_stop_at_previous_decl():
    """def prev\n@[simp] def X — must STOP scanning, not pick up prev's attrs."""
    lines = [
        "@[norm_cast]",
        "def previous",
        "",
        "@[simp]",
        "def current",
    ]
    result = policy.parse_attrs(lines, 4, "def")
    # Should only see @[simp], not @[norm_cast] from previous decl
    assert result == ["simp"], f"Expected ['simp'], got {result}"


def test_protected_modifier():
    """@[simp]\nprotected def X — protected keyword should not block scanning."""
    lines = ["@[simp]", "protected def prot"]
    result = policy.parse_attrs(lines, 1, "def")
    assert result == ["simp"], f"Expected ['simp'], got {result}"


def test_partial_keyword():
    """@[simp]\npartial def X — partial keyword."""
    lines = ["@[simp]", "partial def partial_def"]
    result = policy.parse_attrs(lines, 1, "def")
    assert result == ["simp"], f"Expected ['simp'], got {result}"


def test_no_attributes():
    """def foo — no attributes at all."""
    lines = ["def plain"]
    result = policy.parse_attrs(lines, 0, "def")
    assert result == [], f"Expected [], got {result}"


def test_blank_lines_between_attr_and_def():
    """@[simp]\n\nlemma X — blank line between attr and def."""
    lines = ["@[simp]", "", "lemma spaced"]
    result = policy.parse_attrs(lines, 2, "lemma")
    assert result == ["simp"], f"Expected ['simp'], got {result}"


def test_comment_lines():
    """@[simp]\n-- comment\nlemma X — comment line should not stop scanning."""
    lines = ["@[simp]", "-- a comment", "lemma commented"]
    result = policy.parse_attrs(lines, 2, "lemma")
    assert result == ["simp"], f"Expected ['simp'], got {result}"


def test_multiline_docstring_marker():
    """@[simp]\n/-- doc block\nlemma X — docstring block marker."""
    lines = ["@[simp]", "/-- doc block", "lemma in_doc"]
    result = policy.parse_attrs(lines, 2, "lemma")
    assert result == ["simp"], f"Expected ['simp'], got {result}"


def test_abbrev_keyword():
    """@[simp] abbrev X — abbrev keyword should be recognized."""
    lines = ["@[simp] abbrev my_abbrev"]
    result = policy.parse_attrs(lines, 0, "abbrev")
    assert result == ["simp"], f"Expected ['simp'], got {result}"


if __name__ == "__main__":
    # Run all tests
    import inspect
    module = sys.modules[__name__]
    tests = [obj for name, obj in inspect.getmembers(module)
             if name.startswith("test_") and callable(obj)]

    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"✓ {test.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__}: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__}: {type(e).__name__}: {e}")
            failed += 1

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
