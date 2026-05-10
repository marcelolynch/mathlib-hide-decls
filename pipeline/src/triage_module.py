#!/usr/bin/env python3
"""triage_module.py — for a tier-2 candidate module, identify mechanical
privatization candidates and flag risky ones.

For each candidate decl from `ranked_candidates_lean.jsonl`:
  1. Locate it in the source file (via line-anchored regex).
  2. Classify by source-line pattern:
       - real top-level `def` / `partial def`     → privatizable (mechanical)
       - `instance`                              → flagged (typeclass risk)
       - `structure` field projection            → not directly privatizable
       - `syntax` / `elab` / `attribute`         → not directly privatizable
       - already `private`                       → skip
       - not found by name regex                 → skip (likely synth)
  3. Cross-grep across mathlib (excluding the file) for any reference.
       Catches `_initFn_*` blind spots that the census missed.

Output: a list of (line, name, action) tuples and a printable report.
"""
from __future__ import annotations
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

MLB = paths.MATHLIB
RANKED = paths.RANKED


def module_to_path(m: str) -> Path:
    return MLB / (m.replace(".", "/") + ".lean")


def candidates_for(module: str) -> list[str]:
    """Pull the tier-2 bundle's decl list (synth-aux already filtered)."""
    for line in paths.open_jsonl(RANKED):
        r = json.loads(line)
        if r.get("tier") == "2_bundle" and r.get("module") == module:
            return r["decls"]
    return []


# -- source-classification regex patterns
PAT_PRIV = re.compile(r"^private\s+")
PAT_DEF = re.compile(r"^(partial\s+)?def\s+")
PAT_PARTIAL_DEF = re.compile(r"^partial\s+def\s+")
PAT_INSTANCE = re.compile(r"^instance\b|^\@\[instance\]")
PAT_SYNTAX_LIKE = re.compile(r"^(syntax|elab|notation|macro|attribute)\b")
PAT_STRUCTURE = re.compile(r"^structure\b|^class\b|^inductive\b")


def find_decl(lines: list[str], leaf: str) -> tuple[int, str, str] | None:
    """Locate the decl by leaf name. Returns (lineno, full_line, classification)."""
    pat = re.compile(rf"\b{re.escape(leaf)}\b")
    for i, line in enumerate(lines, start=1):
        # Look for `<keyword> <name>` patterns at column 0 with the leaf in the line
        if not pat.search(line):
            continue
        if PAT_PRIV.match(line) and pat.search(line):
            return (i, line.rstrip(), "ALREADY_PRIVATE")
        if PAT_DEF.match(line) and pat.search(line):
            # Make sure the def name actually matches leaf (not just substring of arg name)
            # A def line looks like: `def NAME` or `partial def NAME`
            m = re.match(r"^(?:partial\s+)?def\s+(\S+?)(?:\s|\(|\[|\:|$)", line)
            if m and m.group(1).rstrip("?") == leaf.rstrip("?"):
                return (i, line.rstrip(), "DEF" if not PAT_PARTIAL_DEF.match(line) else "PARTIAL_DEF")
        if PAT_INSTANCE.match(line) and pat.search(line):
            return (i, line.rstrip(), "INSTANCE")
        if PAT_SYNTAX_LIKE.match(line) and pat.search(line):
            return (i, line.rstrip(), "SYNTAX_LIKE")
    return None


def grep_mathlib_for(name: str, exclude_file: Path) -> list[str]:
    """Return list of files in Mathlib/ that reference name (excluding exclude_file)."""
    safe = re.escape(name)
    cmd = ["grep", "-rln", "--include=*.lean", "-E", rf"\b{safe}\b", str(MLB / "Mathlib")]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        out = result.stdout.strip()
    except subprocess.TimeoutExpired:
        return ["<grep timeout>"]
    if not out:
        return []
    files = out.splitlines()
    rel_excl = str(exclude_file)
    return [f for f in files if f != rel_excl and not f.endswith("/" + exclude_file.name) or False]
    # NB: keep simple — exclude only exact path match


def grep_mathlib_for_strict(name: str, exclude_file: Path) -> list[str]:
    safe = re.escape(name)
    cmd = ["grep", "-rln", "--include=*.lean", "-E", rf"\b{safe}\b", str(MLB / "Mathlib")]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout.strip()
    except subprocess.TimeoutExpired:
        return ["<grep timeout>"]
    if not out:
        return []
    excl = str(exclude_file.resolve())
    return [f for f in out.splitlines() if Path(f).resolve() != Path(excl).resolve()]


def triage(module: str) -> dict:
    path = module_to_path(module)
    if not path.exists():
        return {"module": module, "error": f"file not found: {path}"}
    lines = path.read_text().splitlines(keepends=False)
    cands = candidates_for(module)
    if not cands:
        return {"module": module, "error": "no tier-2 entry found"}

    rows = []
    privatizable = []  # (lineno, leaf, line, classification)
    for fq in cands:
        leaf = fq.rsplit(".", 1)[-1] if "." in fq else fq
        info = find_decl(lines, leaf)
        if info is None:
            rows.append((fq, "—", "NOT_FOUND", "(skip)"))
            continue
        lineno, line, klass = info
        external_refs = grep_mathlib_for_strict(leaf, path)
        # If grep found references in OTHER files, decl is NOT safe even if census says so
        ref_count = len(external_refs)
        if klass == "ALREADY_PRIVATE":
            rows.append((fq, lineno, klass, "skip"))
        elif klass in ("DEF", "PARTIAL_DEF"):
            # Don't pre-filter by grep — leaf names like "data" or "of"
            # produce thousands of false-positive matches. Trust `lake build`
            # as the authoritative gate; report grep count as advisory only.
            note = f"PRIVATIZE  (grep:{ref_count})" if ref_count > 0 else "PRIVATIZE"
            rows.append((fq, lineno, klass, note))
            privatizable.append((lineno, leaf, line, klass))
        else:
            rows.append((fq, lineno, klass, "skip (non-def)"))
    return {"module": module, "path": str(path), "rows": rows, "privatizable": privatizable}


def report(t: dict) -> str:
    if "error" in t:
        return f"# {t['module']}\nERROR: {t['error']}\n"
    out = []
    out.append(f"# {t['module']}")
    out.append(f"  source: {t['path']}")
    out.append(f"  candidates: {len(t['rows'])}; will privatize: {len(t['privatizable'])}")
    out.append("")
    out.append(f"  {'fq_name':<60s} {'line':>5s}  {'class':<16s}  action")
    out.append("  " + "-" * 110)
    for fq, lineno, klass, action in t["rows"]:
        out.append(f"  {fq:<60s} {str(lineno):>5s}  {klass:<16s}  {action}")
    return "\n".join(out)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: triage_module.py <module> [<module> ...]", file=sys.stderr)
        sys.exit(1)
    for m in sys.argv[1:]:
        t = triage(m)
        print(report(t))
        print()
