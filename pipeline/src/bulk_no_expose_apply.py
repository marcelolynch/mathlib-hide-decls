#!/usr/bin/env python3
"""bulk_no_expose_apply.py — apply `@[no_expose]` to internal `def`s in the
modules of the top-K tier-3 hubs, prioritized by score.

The tier-3 analog of bulk_apply.py. Where bulk_apply marks tier-1 candidates
`private`, this script marks ANY `def` inside a tier-3 hub's module
`@[no_expose]`, as long as it passes the attribute / kind / pattern filter.
The iterate-revert loop (bulk_no_expose_iterate.sh) will throw out the ones
that break the build.

Output:
  - Edits .lean files in-place under MATHLIB.
  - Writes data/work/no_expose/manifest.jsonl  — one line per applied decl,
    {file, line_offset, decl_name, kind, hub_module, hub_score}
  - Writes data/work/no_expose/skipped.jsonl   — declined candidates + reason

Per-decl filter (apply this only if ALL true):
  - kind == "def"  (no_expose is def-only — see methodology)
  - decl is not already `private`
  - no `@[no_expose]` already present
  - no forbidden_attrs (per policy.toml: reducible / implicit_reducible /
    inline / deprecated)
  - no `@[match_pattern]`     (body needed for pattern matching)
  - no `@[simp]` / `@[simps]` / `@[simps!]` (body may be unfolded by simp)
  - no `@[ext]`               (extensionality machinery references body)
  - no `@[instance]` and not declared with `instance` keyword
                              (instance bodies are part of the typeclass interface)
  - no `@[coe]`               (coercion bodies are usually inspected)
  - no notation declaration referencing the decl in the same file
    (parser-table records the bare name; can't resolve mangled forms)
"""
from __future__ import annotations

import gzip
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
import policy  # noqa: E402

MATHLIB = paths.MATHLIB
RANKED = paths.RANKED
CENSUS = paths.CENSUS
WORK = paths.DATA / "work" / "no_expose"
MANIFEST = WORK / "manifest.jsonl"
SKIPPED = WORK / "skipped.jsonl"

# Top-K tier-3 hubs to consider.  Modules of these hubs become the candidate
# pool; each module contributes every `def` that passes the filter.
TOP_K = int(__import__("os").environ.get("BULK_NO_EXPOSE_TOP_K", "1000"))

# Attributes whose presence on a decl disqualifies it for `@[no_expose]`.
# (Distinct from policy.toml's hard-block lists; this set is specific to the
# new module system's body-exposure semantics.)
DISQUALIFYING_ATTRS = {
    "match_pattern", "simp", "simps", "simps!", "ext", "instance",
    "coe", "reducible", "implicit_reducible", "inline", "deprecated",
    "norm_cast", "norm_num", "gcongr", "mono", "fun_prop", "positivity",
    "aesop", "macro", "macro_rules", "tactic", "elab_rules", "term_parser",
    "builtin_simp", "builtin_simp_attr", "builtin_term_parser",
    "to_additive",  # privatizing the multiplicative side would orphan additive sibling
    "to_dual",      # same generator pattern as to_additive (Order/* uses this)
    "push", "push_cast",  # extension-registered rewriting hints
    "mk_iff", "mk_simps", "induction_eliminator", "cases_eliminator",
    "irreducible", "expose",  # `expose` shouldn't co-occur with no_expose
    "default_instance", "class_abbrev", "ext_iff", "structure",
    "norm_num_ext", "norm_cast_ext", "ext_iff",
}

DEF_LINE_RE = re.compile(
    r"^(?P<indent>\s*)"
    r"(?:@\[[^\]]*\]\s*)*"
    r"(?:(?:private|protected|noncomputable|meta|partial|unsafe)\s+)*"
    r"(?P<kind>def|theorem|lemma)\s+"
    r"(?P<name>[\w«»'!?₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹]"
    r"(?:[\w.«»'!?₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹])*)"
)
ALREADY_PRIVATE_RE = re.compile(r"^\s*(?:@\[[^\]]*\]\s*)*(?:[a-z]+\s+)*private\b")
NO_EXPOSE_LINE_RE = re.compile(r"^\s*@\[\s*(?:[^,\]]*,\s*)?no_expose\b")
NOTATION_LINE_RE = re.compile(
    r"^\s*(?:@\[[^\]]*\]\s*)*"
    r"(?:infix|infixl|infixr|prefix|postfix|notation)\b[^=]*=>\s*(?P<name>\S+)"
)
ATTR_LINE_RE = re.compile(r"@\[([^\]]+)\]")


def load_attrs_around(src_lines: list[str], i: int) -> set[str]:
    """Scan attributes attached to the decl at line i.

    Handles multi-line attribute blocks (`@[to_dual\\n.../-- ... -/]`) by
    walking back until bracket balance reaches zero, then taking the
    leading identifier of each `@[…]` block.

    A marker `__MULTILINE__` is added to the result if any multi-line
    attribute or unbalanced-bracket region is detected — caller can use
    this to skip the decl conservatively.
    """
    attrs: set[str] = set()
    # Walk up at most 20 lines; collect attr blocks tolerating multi-line.
    bracket_depth = 0
    block_buf: list[str] = []
    j = i
    line0 = src_lines[i].rstrip("\n").rstrip()
    # Same-line attrs on the def line itself
    for m in ATTR_LINE_RE.finditer(line0):
        for part in m.group(1).split(","):
            ident = part.strip().split()[0].split("(")[0]
            if ident:
                attrs.add(ident.lstrip("@"))

    j = i - 1
    walked = 0
    while j >= 0 and walked < 20:
        walked += 1
        line = src_lines[j].rstrip("\n").rstrip()
        stripped = line.strip()
        if not line:
            break
        if line.startswith("--") and not stripped.startswith("--"):
            break
        opens = line.count("[")
        closes = line.count("]")
        bracket_depth += closes - opens
        # If we have a bracket imbalance going INTO this line (closes > opens)
        # then we crossed into the middle of a multi-line attr block.
        if bracket_depth != 0:
            attrs.add("__MULTILINE__")
        # Capture per-line @[...] starts (works for single-line attrs)
        for m in ATTR_LINE_RE.finditer(line):
            for part in m.group(1).split(","):
                ident = part.strip().split()[0].split("(")[0]
                if ident:
                    attrs.add(ident.lstrip("@"))
        # If `@[` on the line and depth is 0 again after processing, single-line attr — OK
        # Decide whether to keep walking up:
        is_modifier = stripped in {"noncomputable", "partial", "unsafe", "protected"}
        is_attr_open = stripped.startswith("@[")
        is_attr_close = stripped.endswith("]")
        is_setopt = stripped.startswith("set_option") and stripped.endswith(" in")
        is_decl = re.match(r"^\s*(def|theorem|lemma|abbrev|structure|inductive|class|instance|opaque)\b", line)
        if is_decl:
            break
        if not (is_modifier or is_attr_open or is_attr_close or is_setopt or bracket_depth != 0):
            break
        j -= 1
    if bracket_depth != 0:
        attrs.add("__MULTILINE__")
    return attrs


def collect_notation_targets(src_lines: list[str]) -> set[str]:
    """Find all decls bound to notation in the file (`infixl ` ::ᵣ ` => cons`)."""
    out: set[str] = set()
    for line in src_lines:
        m = NOTATION_LINE_RE.match(line)
        if m:
            # Take last component of dotted name
            name = m.group("name").strip().rstrip(",;)")
            out.add(name.rsplit(".", 1)[-1])
    return out


def main() -> int:
    # Load tier-3 ranked list
    with paths.open_jsonl(RANKED) as f:
        hubs = []
        for line in f:
            r = json.loads(line)
            if r.get("tier") != "3_encap":
                continue
            hubs.append(r)
    print(f"loaded {len(hubs):,} tier-3 hubs", file=sys.stderr)

    # Top-K hubs by score (already sorted in rerank.py output, but re-sort defensively)
    hubs.sort(key=lambda r: -r.get("score", 0.0))
    top = hubs[:TOP_K]
    target_modules: dict[str, float] = {}
    for h in top:
        # Use max score across hubs in same module
        m = h["defining_module"]
        if m not in target_modules or h["score"] > target_modules[m]:
            target_modules[m] = h["score"]
    print(f"top {TOP_K} hubs → {len(target_modules)} unique modules", file=sys.stderr)

    # Load census: defs AND theorems in target modules.
    # Defs get @[no_expose]; theorems get `private` (PR-38702 pattern).
    by_module_defs: dict[str, dict[str, dict]] = defaultdict(dict)
    with paths.open_jsonl(CENSUS) as f:
        for line in f:
            r = json.loads(line)
            m = r["defining_module"]
            if m not in target_modules:
                continue
            if r.get("kind") not in ("def", "theorem"):
                continue
            by_module_defs[m][r["fq_name"]] = r
    n_decls = sum(len(v) for v in by_module_defs.values())
    print(f"census: {n_decls:,} def+theorem decls in target modules", file=sys.stderr)

    WORK.mkdir(parents=True, exist_ok=True)
    manifest_f = MANIFEST.open("w")
    skipped_f = SKIPPED.open("w")
    n_applied = n_skipped = 0

    # Process modules in score order
    for module in sorted(target_modules, key=lambda m: -target_modules[m]):
        path_lean = MATHLIB / (module.replace(".", "/") + ".lean")
        if not path_lean.exists():
            # Try with trailing-underscore alias
            alt = MATHLIB / (module.replace(".", "/") + "_.lean")
            if alt.exists():
                path_lean = alt
            else:
                continue

        src = path_lean.read_text().splitlines(keepends=True)
        src_no_ends = [ln.rstrip("\n").rstrip() for ln in src]
        defs_in_module = by_module_defs.get(module, {})

        # Pre-pass: find notation targets to exclude
        notation_targets = collect_notation_targets(src_no_ends)

        # Track namespace
        ns_stack: list[str] = []
        # Plan inserts as (line_idx, indent, decl_name, fq_name, kind)
        plans: list[tuple[int, str, str, str, str]] = []

        for i, line in enumerate(src):
            stripped = line.strip()
            if stripped.startswith("namespace "):
                ns_stack.append(stripped[len("namespace "):].split()[0])
                continue
            if stripped.startswith("end ") and len(stripped.split()) >= 2:
                tok = stripped.split()[1]
                if ns_stack and ns_stack[-1] == tok:
                    ns_stack.pop()
                continue
            m = DEF_LINE_RE.match(line)
            if not m:
                continue
            if ALREADY_PRIVATE_RE.match(line) or NO_EXPOSE_LINE_RE.match(line):
                continue
            # Check previous line for existing @[no_expose] or `private`
            if i > 0 and NO_EXPOSE_LINE_RE.match(src[i-1]):
                continue
            leaf = m.group("name").split(".")[-1]
            # Resolve fq via namespace
            for k in range(len(ns_stack), -1, -1):
                prefix = ".".join(ns_stack[:k])
                fq = f"{prefix}.{leaf}" if prefix else leaf
                if fq in defs_in_module:
                    r = defs_in_module[fq]
                    break
            else:
                continue

            # Skip if bound to notation
            if leaf in notation_targets:
                skipped_f.write(json.dumps({"fq_name": r["fq_name"], "module": module,
                                            "line": i+1, "reason": "notation-target"}) + "\n")
                n_skipped += 1
                continue
            # Forbidden attrs from census
            if r.get("forbidden_attrs"):
                skipped_f.write(json.dumps({"fq_name": r["fq_name"], "module": module,
                                            "line": i+1, "reason": f"census-forbidden-attrs: {r['forbidden_attrs']}"}) + "\n")
                n_skipped += 1
                continue
            # Source-side attributes
            attrs = load_attrs_around(src_no_ends, i)
            if "__MULTILINE__" in attrs:
                skipped_f.write(json.dumps({"fq_name": r["fq_name"], "module": module,
                                            "line": i+1, "reason": "multiline-attr-block"}) + "\n")
                n_skipped += 1
                continue
            blocked = attrs & DISQUALIFYING_ATTRS
            if blocked:
                skipped_f.write(json.dumps({"fq_name": r["fq_name"], "module": module,
                                            "line": i+1, "reason": f"disqualifying-attr: {','.join(sorted(blocked))}"}) + "\n")
                n_skipped += 1
                continue

            plans.append((i, m.group("indent"), leaf, r["fq_name"], m.group("kind")))

        # Apply plans in reverse line order so indices stay stable
        for line_idx, indent, decl_name, fq_name, kind in sorted(plans, key=lambda p: -p[0]):
            # Walk back past modifier keywords to find insertion point.
            j = line_idx
            while j > 0:
                prev = src[j-1].rstrip("\n").rstrip()
                if prev.strip() in {"noncomputable", "partial", "unsafe", "protected"}:
                    j -= 1; continue
                if (prev.strip().startswith("@[") and prev.strip().endswith("]")):
                    j -= 1; continue
                if (prev.strip().startswith("set_option") and prev.strip().endswith(" in")):
                    j -= 1; continue
                break
            if kind == "def":
                # Insert `@[no_expose]` line above the topmost modifier/attr.
                insert_line = f"{indent}@[no_expose]\n"
                src.insert(j, insert_line)
                action = "no_expose"
                # The original def keyword line moved down by 1.
                edited_line = j
            else:
                # Theorem / lemma: prefix `private` on the keyword line itself.
                # Lean modifier order: any @[…] / set_option-in ABOVE,
                # then `private`, then `noncomputable`, then the keyword.
                # Locate the keyword line: it's `line_idx` (the original match),
                # but if there are `noncomputable`/etc. modifiers in between j..line_idx,
                # `private` must come BEFORE those modifiers on the keyword line.
                # We rewrite the def keyword line so it starts with `private`.
                kw_line = line_idx
                kw_text = src[kw_line]
                kw_indent_match = re.match(r"^(\s*)", kw_text)
                kw_indent = kw_indent_match.group(1) if kw_indent_match else ""
                body = kw_text[len(kw_indent):]
                src[kw_line] = f"{kw_indent}private {body}"
                insert_line = None  # in-place rewrite, no insertion
                action = "private"
                edited_line = kw_line
            manifest_f.write(json.dumps({
                "file": str(path_lean.relative_to(MATHLIB)),
                "module": module,
                "decl_name": decl_name,
                "fq_name": fq_name,
                "kind": kind,
                "action": action,
                "line_inserted_at": edited_line + 1,
                "inserted_a_line": insert_line is not None,
                "hub_score": target_modules[module],
            }) + "\n")
            n_applied += 1

        if plans:
            path_lean.write_text("".join(src))

    manifest_f.close()
    skipped_f.close()
    print(f"applied @[no_expose] to {n_applied} decls; "
          f"skipped {n_skipped}", file=sys.stderr)
    print(f"manifest: {MANIFEST}")
    print(f"skipped:  {SKIPPED}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
