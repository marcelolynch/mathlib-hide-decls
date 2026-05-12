#!/usr/bin/env python3
"""Per-module attribute counts from a mathlib4 source checkout.

Walks every `.lean` file under `Mathlib/`, counts:
  - n_decls          : declaration headers (`def`, `theorem`, `lemma`,
                       `abbrev`, `structure`, `inductive`, `class`,
                       `instance`)
  - n_to_additive    : `@[to_additive ...]` markers (one per attribute,
                       not per generated sibling)
  - n_instances      : `instance` declaration headers
  - n_simp           : `@[simp]` markers (incl. combined attribute lists
                       like `@[simp, refl]`)
  - n_simps          : `@[simps]` / `@[simps!]` markers

Writes `data/module_attrs.json` (path overridable on the CLI). Consumed
by `rerank.py` to filter out tier-3 hub candidates whose defining module
is dominated by `@[to_additive]`, by `instance` declarations, etc.

Usage:
    python pipeline/scripts/scan_module_attrs.py <mathlib4-path> [<out>]

If <mathlib4-path> is omitted, defaults to /Users/chelo/mathlib4 (the
local checkout). The output JSON shape is:

    { "<Mathlib.Foo.Bar>": { "n_decls": 123, "n_to_additive": 45,
                             "n_instances": 12, "n_simp": 30,
                             "n_simps": 0 }, ... }
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

DECL_HEADER = re.compile(
    r"^\s*(?:protected\s+|private\s+|noncomputable\s+|partial\s+|unsafe\s+|@\[[^\]]*\]\s*)*"
    r"(?P<kw>def|theorem|lemma|abbrev|structure|inductive|class|instance|opaque)\b"
)
TO_ADDITIVE = re.compile(r"^\s*@\[(?:[^\]]*\b)?to_additive\b")
INSTANCE_HEAD = re.compile(r"^\s*(?:protected\s+|private\s+|noncomputable\s+)*instance\b")
SIMP_ATTR = re.compile(r"^\s*@\[(?:[^\]]*,\s*)?simp\b(?![a-zA-Z_!])")
SIMPS_ATTR = re.compile(r"^\s*@\[(?:[^\]]*,\s*)?simps!?\b")


def module_of(path: Path, mathlib_root: Path) -> str:
    """Convert filesystem path to module name: Mathlib/Algebra/Foo.lean → Mathlib.Algebra.Foo."""
    rel = path.relative_to(mathlib_root).with_suffix("")
    return ".".join(rel.parts)


def scan_file(path: Path) -> dict[str, int]:
    n_decls = n_to_add = n_inst = n_simp = n_simps = 0
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {"n_decls": 0, "n_to_additive": 0, "n_instances": 0,
                "n_simp": 0, "n_simps": 0}
    for line in text.splitlines():
        if DECL_HEADER.match(line):
            n_decls += 1
        if TO_ADDITIVE.match(line):
            n_to_add += 1
        if INSTANCE_HEAD.match(line):
            n_inst += 1
        if SIMP_ATTR.match(line):
            n_simp += 1
        if SIMPS_ATTR.match(line):
            n_simps += 1
    return {"n_decls": n_decls, "n_to_additive": n_to_add,
            "n_instances": n_inst, "n_simp": n_simp, "n_simps": n_simps}


def main(argv: list[str]) -> int:
    mathlib_path = Path(argv[1] if len(argv) > 1 else "/Users/chelo/mathlib4")
    out_path = Path(argv[2] if len(argv) > 2
                    else "/Users/chelo/mathlib-hide-decls/data/module_attrs.json")
    mathlib_root = mathlib_path / "Mathlib"
    if not mathlib_root.is_dir():
        print(f"error: {mathlib_root} is not a directory", file=sys.stderr)
        return 2

    result: dict[str, dict[str, int]] = {}
    for lean_file in sorted(mathlib_root.rglob("*.lean")):
        mod = module_of(lean_file, mathlib_path)
        data = scan_file(lean_file)
        result[mod] = data
        # The census normalises certain mathlib filenames by stripping a
        # trailing underscore (`Grp_.lean` → module name `…Grp`). The exact
        # rule lives in Lean's elaborator; aliasing here keeps the rerank
        # lookup tolerant without re-running the census.
        if mod.endswith("_"):
            alias = mod[:-1]
            if alias not in result:
                result[alias] = data

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, separators=(",", ":")))
    print(f"wrote {out_path}  ({len(result):,} modules)")
    # Quick sanity print
    sample = sorted(result.items(), key=lambda kv: -kv[1]["n_to_additive"])[:5]
    print("top-5 by @[to_additive] count:")
    for m, d in sample:
        frac = d["n_to_additive"] / max(d["n_decls"], 1)
        print(f"  {d['n_to_additive']:>4}/{d['n_decls']:<4} ({frac:.0%})  {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
