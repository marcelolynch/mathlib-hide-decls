"""policy.py — shared loader for policy.toml.

Three consumers (rerank_lean.py, dashboard/build_dashboard.py,
pr1/iterate_bundle.sh's Python heredoc) all import from here. Adding or
removing a forbidden attribute / name pattern means editing policy.toml
only — never the consumers.

If `tomllib` is unavailable (Python < 3.11) we fall back to a hand-rolled
`tomllib_min` parser sufficient for the schema in policy.toml. The parser
is intentionally minimal — it parses table headers, string assignments,
list-of-string assignments, and integer assignments. No support for
nested tables, datetimes, multi-line strings, etc. (We don't need them.)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

_DEFAULT_PATH = Path(__file__).resolve().parents[1] / "policy.toml"


def _parse_minimal_toml(text: str) -> dict[str, Any]:
    """Minimal TOML parser sufficient for our policy.toml.

    Supports: `[table]` headers, `key = "string"`, `key = ["a", "b", …]` (one
    per line OR multi-line, non-nested), `key = 123`, `# comment` lines.
    """
    out: dict[str, dict[str, Any]] = {}
    cur: dict[str, Any] | None = None
    pending_key: str | None = None
    pending_list: list[str] | None = None
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        if pending_list is not None:
            # collecting list items
            for tok in re.findall(r'"([^"]*)"', line):
                pending_list.append(tok)
            if line.rstrip().endswith("]"):
                cur[pending_key] = pending_list  # type: ignore[index]
                pending_key = None
                pending_list = None
            continue
        m = re.match(r"^\[([\w.]+)\]\s*$", line.strip())
        if m:
            cur = out.setdefault(m.group(1), {})
            continue
        m = re.match(r'^(\w+)\s*=\s*(.*)$', line.strip())
        if not m or cur is None:
            continue
        key, val = m.group(1), m.group(2).strip()
        if val.startswith('"') and val.endswith('"'):
            cur[key] = val[1:-1]
        elif val == "true":
            cur[key] = True
        elif val == "false":
            cur[key] = False
        elif re.match(r"^-?\d+$", val):
            cur[key] = int(val)
        elif val.startswith("[") and val.endswith("]"):
            cur[key] = [tok for tok in re.findall(r'"([^"]*)"', val[1:-1])]
        elif val.startswith("["):
            pending_key = key
            pending_list = [tok for tok in re.findall(r'"([^"]*)"', val[1:])]
        else:
            cur[key] = val
    return out


def _load_toml(path: Path) -> dict[str, Any]:
    text = path.read_text()
    try:
        import tomllib  # Python 3.11+
        return tomllib.loads(text)
    except ImportError:
        return _parse_minimal_toml(text)


_cache: dict[str, Any] | None = None


def get_policy(path: Path | None = None) -> dict[str, Any]:
    """Return the parsed policy.toml as a nested dict. Cached after first call."""
    global _cache
    if _cache is None or path is not None:
        p = path or _DEFAULT_PATH
        _cache = _load_toml(p)
    return _cache


# Convenience accessors. Each returns a frozen-ish view of policy.toml.

def hard_blocks() -> dict[str, Any]:
    return get_policy().get("hard_blocks", {})


def never_hide_kinds() -> set[str]:
    return set(hard_blocks().get("never_hide_kinds", []))


def forbidden_attrs() -> set[str]:
    return set(hard_blocks().get("forbidden_attrs", []))


def build_rejected_attrs() -> set[str]:
    return set(hard_blocks().get("build_rejected_attrs", []))


def all_blocked_attrs() -> set[str]:
    """Used by iterate_bundle.sh's apply-private filter — rejects both the
    semantic-risk attrs AND the build-rejected attrs at edit time."""
    return forbidden_attrs() | build_rejected_attrs()


def forbidden_name_patterns() -> set[str]:
    return set(hard_blocks().get("forbidden_name_patterns", []))


def auto_synth_suffixes() -> tuple[str, ...]:
    return tuple(hard_blocks().get("auto_synth_suffixes", []))


def auto_synth_inner() -> tuple[str, ...]:
    return tuple(hard_blocks().get("auto_synth_inner", []))


def is_synthesized_aux(name: str) -> bool:
    """True if the decl name looks elaborator-auto-generated (cannot be
    privatized independently — visibility tracks the parent)."""
    suff = auto_synth_suffixes()
    if any(name.endswith(s) for s in suff):
        return True
    inner = auto_synth_inner()
    if any(s in name for s in inner):
        return True
    return False


def parse_attrs(src_lines: list[str], def_line_idx: int, kind_keyword: str) -> list[str]:
    """Extract all attribute tokens applying to a def/lemma/theorem/abbrev.

    Scans two regions:
      1. Same-line @[…] groups before the kind keyword (e.g., `@[simp] def X`)
      2. Preceding contiguous lines that are @[…] blocks, doc comments, or blanks

    Returns a list of attribute tokens (e.g., ['simp', 'norm_cast']). Empty if
    no attributes found.

    Args:
        src_lines: source code lines (list of strings, no keepends)
        def_line_idx: index in src_lines of the def/lemma/theorem/abbrev line
        kind_keyword: the keyword that marks the decl (e.g., "def", "lemma",
                      "theorem", "abbrev")

    Examples:
        >>> lines = ["@[simp] def foo"]
        >>> parse_attrs(lines, 0, "def")
        ['simp']

        >>> lines = ["@[simp, norm_cast] lemma bar"]
        >>> parse_attrs(lines, 0, "lemma")
        ['simp', 'norm_cast']

        >>> lines = ["@[simp]", "lemma baz"]
        >>> parse_attrs(lines, 1, "lemma")
        ['simp']

        >>> lines = ["/-- doc --/", "@[simp]", "theorem qux"]
        >>> parse_attrs(lines, 2, "theorem")
        ['simp']
    """
    import re

    attrs: list[str] = []
    cur_line = src_lines[def_line_idx]

    # 1. Scan for same-line @[…] groups BEFORE the kind keyword.
    #    Lines like `@[simp, norm_cast] lemma X` are common idiom.
    kind_pos = cur_line.find(" " + kind_keyword + " ")
    if kind_pos < 0:
        kind_pos = cur_line.find(" " + kind_keyword + "(")
    if kind_pos < 0:
        # kind_keyword may be at the start of the line (no leading @[…])
        kind_pos = cur_line.find(kind_keyword)
        if kind_pos == 0 or (kind_pos > 0 and cur_line[kind_pos - 1] in " \t"):
            kind_pos = 0
        else:
            kind_pos = cur_line.rfind(kind_keyword)
    if kind_pos < 0:
        kind_pos = len(cur_line)

    head = cur_line[:kind_pos]
    # Find all @[…] blocks in the prefix
    attr_re = re.compile(r"@\[([^\]]*)\]")
    for m in attr_re.finditer(head):
        attr_block = m.group(1)
        # Split on commas and extract token names
        # Each token may carry args like `deprecated foo (since := "...")`
        # We extract just the base names (A-Za-z_... before any parens or spaces)
        for token in attr_block.split(","):
            token = token.strip()
            # Extract the first token (identifier)
            tok_match = re.match(r"([A-Za-z_][A-Za-z_0-9]*[!?]?)", token)
            if tok_match:
                attrs.append(tok_match.group(1))

    # 2. Scan preceding lines that are @[…] blocks, doc comments, or blanks.
    #    Stop at the first non-attribute non-comment non-blank line.
    #    Scan up to 16 lines to avoid runaway on huge docstrings.
    for k in range(def_line_idx - 1, max(-1, def_line_idx - 16), -1):
        line_k = src_lines[k].rstrip()
        stripped_k = line_k.lstrip()

        if stripped_k == "":
            # blank line — keep scanning
            continue

        if stripped_k.startswith("@[") and "]" in stripped_k:
            # attribute block (may span lines, but we only care about lines
            # where @[ and ] are both present)
            inside = stripped_k[2 : stripped_k.index("]")]
            for token in inside.split(","):
                token = token.strip()
                tok_match = re.match(r"([A-Za-z_][A-Za-z_0-9]*[!?]?)", token)
                if tok_match:
                    attrs.append(tok_match.group(1))
            continue

        if stripped_k.startswith("--") or stripped_k.startswith("/-"):
            # comment line — keep scanning
            continue

        if stripped_k.startswith("-/") or stripped_k.endswith("-/"):
            # doc comment closer or inline marker — keep scanning
            continue

        if "/--" in stripped_k:
            # multi-line docstring closer/opener — keep scanning
            continue

        # Any other line is a previous decl or statement; stop scanning.
        break

    return attrs


def forbidden_module_prefixes() -> tuple[str, ...]:
    """Module path prefixes for tier-1 candidates to skip (e.g. Mathlib.Tactic.*).

    These modules are dominated by extension-registered helpers that will
    revert during iterate-and-revert, producing noise without yield.
    """
    return tuple(hard_blocks().get("forbidden_module_prefixes", []))


def tier_1() -> dict[str, Any]:
    return get_policy().get("tier_1", {})


def tier_2() -> dict[str, Any]:
    return get_policy().get("tier_2", {})


def tier_3() -> dict[str, Any]:
    return get_policy().get("tier_3", {})


if __name__ == "__main__":
    import json
    print(json.dumps(get_policy(), indent=2))
