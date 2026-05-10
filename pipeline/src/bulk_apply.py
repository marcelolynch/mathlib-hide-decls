#!/usr/bin/env python3
"""bulk_apply.py — apply `private` to every tier-1 candidate across mathlib
in one pass. Intended to be run once on a clean master worktree.

Output:
  - Edits the .lean files in-place under MATHLIB.
  - Writes data/work/manifest.jsonl: one line per applied privatization
    with {fq_name, module, file, line, leaf, kind} for the revert pass.
  - Writes data/work/skipped.jsonl: candidates declined to apply, with reason.

Per-decl logic:
  - namespace-aware leaf matching (handles dot-method dispatch ambiguity)
  - forbidden-attribute pre-filter (read from policy.toml)
  - simps_projection name-pattern filter (read from policy.toml)
  - preserves `partial def`

Does NOT do:
  - line-wrapping for 100-char style budget (line-length is purely cosmetic)
  - lake-build verification (that's the iterate-revert step)
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

# Local imports.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402
import policy  # noqa: E402

MATHLIB = paths.MATHLIB
RANKED = paths.RANKED
MANIFEST = paths.MANIFEST
SKIPPED = paths.SKIPPED

DEF_LINE_RE = re.compile(
    r"^(?P<indent>\s*)"
    # optional @[..] attribute prefix (one or more) on the same line
    r"(?:@\[[^\]]*\]\s*)*"
    # any combination of these keywords in any order (greedy match)
    r"(?:(?:private|protected|noncomputable|meta|partial|unsafe)\s+)*"
    r"(?P<kind>def|abbrev|theorem|lemma)\s+"
    # name: one identifier-char-plus-extras, then any number of identifier-or-dot
    # chars. (No trailing \b — our class includes ' and unicode chars that aren't
    # word characters, so \b would chop the match early.)
    r"(?P<name>[\w«»'!?₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹]"
    r"(?:[\w.«»'!?₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹])*)"
)
# Sub-patterns to detect already-private (so we don't double-prefix) and to
# preserve the original `partial`/`noncomputable` wrappers.
ALREADY_PRIVATE_RE = re.compile(r"^\s*(?:@\[[^\]]*\]\s*)*(?:[a-z]+\s+)*private\b")


def split_fq(fq: str) -> tuple[list[str], str]:
    """Split a dotted fq into (namespace_segments, leaf)."""
    parts = fq.split(".")
    return parts[:-1], parts[-1]


def main() -> int:
    fa = policy.all_blocked_attrs()
    fnp = policy.forbidden_name_patterns()

    # Group tier-1 candidates by defining_module
    by_module: dict[str, list[dict]] = defaultdict(list)
    with paths.open_jsonl(RANKED) as f:
        for line in f:
            r = json.loads(line)
            if r.get("tier") != "1_solo":
                continue
            by_module[r["defining_module"]].append(r)
    print(f"loaded {sum(len(v) for v in by_module.values())} tier-1 decls "
          f"across {len(by_module)} modules", file=sys.stderr)

    paths.ensure_work_dir()
    manifest_f = MANIFEST.open("w")
    skipped_f = SKIPPED.open("w")
    n_applied = 0
    n_skipped = 0
    n_files = 0

    for module, decls in sorted(by_module.items()):
        path_lean = MATHLIB / (module.replace(".", "/") + ".lean")
        if not path_lean.exists():
            for d in decls:
                skipped_f.write(json.dumps({"fq_name": d["fq_name"],
                                            "module": module,
                                            "reason": "file-not-found"}) + "\n")
                n_skipped += 1
            continue

        src = path_lean.read_text().splitlines(keepends=True)
        cand_set = {d["fq_name"]: d for d in decls}
        ns_stack: list[str] = []
        priv_lines: list[tuple[int, str, str]] = []  # (line_idx, fq, kind)

        # Pass over the file: track namespace via `namespace X` / `end X`,
        # match `def`/`abbrev` lines, identify which fq this is, and apply
        # `private` if the fq is in our candidate set.
        for i, line in enumerate(src):
            stripped = line.strip()
            if stripped.startswith("namespace "):
                ns_stack.append(stripped[len("namespace "):].split()[0])
                continue
            if stripped.startswith("end "):
                tok = stripped[len("end "):].split()
                if tok and ns_stack and ns_stack[-1] == tok[0]:
                    ns_stack.pop()
                continue
            m = DEF_LINE_RE.match(line)
            if not m:
                continue
            if ALREADY_PRIVATE_RE.match(line):
                continue  # already private
            leaf = m.group("name")
            # Try every namespace prefix to find the candidate's fq
            fq_candidates = []
            for k in range(len(ns_stack), -1, -1):
                prefix = ".".join(ns_stack[:k])
                fq_candidates.append(f"{prefix}.{leaf}" if prefix else leaf)
            matched = next((fq for fq in fq_candidates if fq in cand_set), None)
            if not matched:
                continue
            r = cand_set[matched]

            # Forbidden-attribute pre-filter using the shared parser from policy.py.
            # This scans both same-line and preceding-line @[…] groups.
            src_no_ends = [ln.rstrip("\n").rstrip() for ln in src]
            attrs_seen = policy.parse_attrs(src_no_ends, i, m.group("kind"))
            blocked_attrs = [a for a in attrs_seen if a in fa]
            if blocked_attrs:
                skipped_f.write(json.dumps({
                    "fq_name": matched,
                    "module": module,
                    "line": i + 1,
                    "reason": f"forbidden-attr: {','.join(blocked_attrs)}",
                }) + "\n")
                n_skipped += 1
                continue

            # Forbidden name pattern (simps_projection etc.)
            np = r.get("name_pattern")
            if np in fnp:
                skipped_f.write(json.dumps({
                    "fq_name": matched,
                    "module": module,
                    "line": i + 1,
                    "reason": f"forbidden-name-pattern: {np}",
                }) + "\n")
                n_skipped += 1
                continue

            # Apply: prefix `private ` BEFORE any modifiers but AFTER
            # `@[…]` attribute groups, to match the Lean-conventional order
            # `private protected noncomputable def`.  Find the position right
            # after the last `@[…]` group on the line.
            insert_pos = len(m.group("indent"))
            attr_re = re.compile(r"\s*@\[[^\]]*\]")
            scan = insert_pos
            while True:
                am = attr_re.match(line, scan)
                if not am:
                    break
                scan = am.end()
            insert_pos = scan
            # If there's a leading space after the @[..]'s, skip it
            while insert_pos < len(line) and line[insert_pos] == " ":
                insert_pos += 1
            src[i] = line[:insert_pos] + "private " + line[insert_pos:]
            priv_lines.append((i + 1, matched, m.group("kind")))
            manifest_f.write(json.dumps({
                "fq_name": matched,
                "module": module,
                "file": str(path_lean.relative_to(MATHLIB)),
                "line": i + 1,
                "leaf": leaf,
                "kind": m.group("kind"),
            }) + "\n")
            n_applied += 1

        if priv_lines:
            path_lean.write_text("".join(src))
            n_files += 1

    manifest_f.close()
    skipped_f.close()
    print(f"applied: {n_applied}", file=sys.stderr)
    print(f"skipped: {n_skipped}", file=sys.stderr)
    print(f"files modified: {n_files}", file=sys.stderr)
    print(f"manifest: {MANIFEST}", file=sys.stderr)
    print(f"skipped:  {SKIPPED}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
