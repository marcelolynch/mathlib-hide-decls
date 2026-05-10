#!/usr/bin/env python3
"""bulk_revert.py — parse a failing `lake build` log and revert the
privatizations that caused the failures.

Recognized error patterns:
  - "Cannot add attribute [...]: Declaration X.Y.Z must be public"
    → revert the privatization of X.Y.Z
  - "Unknown identifier `X.Y`" / "Unknown constant `X.Y`"
    → revert privatization of X.Y if in manifest
  - "A private declaration `X.Y` exists" (resolution conflict)
  - "Invalid field `f`: ..."  → revert any manifest entry whose leaf is `f`
  - "(kernel) declaration has metavariables 'X'" (instance synthesis)
  - "compiler IR check failed at `X`"
  - "Failed to rewrite using equation theorems for `X`"
  - "failed to synthesize <Class>"  (class-instance synthesis failure)
  - "unknown projection `X`"
  - Module-wide trigger for cascading errors that don't directly name a
    decl (parser breakage, unsolved goals, simp no-progress, etc.):
    every manifest entry from the failing module is reverted.

Outputs:
  - data/work/reverts.jsonl: one line per revert,
    {fq_name, file, line, reason}.
  - Edits .lean files in-place by stripping the `private ` prefix that
    bulk_apply.py added.

Usage:
  python3 bulk_revert.py path/to/build.log
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# Local imports.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

MATHLIB = paths.MATHLIB
MANIFEST = paths.MANIFEST
REVERTS = paths.REVERTS


def load_manifest() -> tuple[dict[str, list[dict]], list[dict]]:
    """Return (fq_name → list[row], all_rows).

    fq_name is NOT unique in the manifest: the same dotted name can be
    declared under different namespace contexts in the same file (e.g.
    `DividedPowers.Quotient.dpow` once at line 554, again at line 635).
    The previous implementation keyed a flat dict and silently dropped
    duplicate rows, which made module-wide and INVALID_FIELD reverts skip
    them. Track all rows per fq_name and iterate the full list everywhere.
    """
    by_fq: dict[str, list[dict]] = defaultdict(list)
    all_rows: list[dict] = []
    if MANIFEST.exists():
        for line in MANIFEST.open():
            r = json.loads(line)
            by_fq[r["fq_name"]].append(r)
            all_rows.append(r)
    return by_fq, all_rows


def parse_errors(log_path: Path) -> set[str]:
    """Read the build log and extract the fq_names that should be reverted.

    Patterns we recognize:
      - "Cannot add attribute …: Declaration `_private.MODULE.0.NAME` must be public"
      - "Cannot add attribute …: Declaration `NAME` must be public"
      - "Unknown identifier 'NAME'" — but only if NAME is in our manifest
      - "Unknown constant `NAME`" — same caveat
    """
    text = log_path.read_text()
    fqs: set[str] = set()
    # Modules that should be wholesale-reverted (any error pattern that doesn't
    # directly name a decl, e.g. parser/syntax breakage from privatized
    # `parser declaration`).
    revert_modules: set[str] = set()

    def add_unprivate(name: str):
        # Lean wraps private decls as `_private.MODULE.0.LEAF` in error
        # messages; strip the wrapper if present so we look up by the
        # original fq_name.
        m = re.match(r"_private\.[\w.]+\.0\.([\w.'!?«»]+)", name)
        clean = m.group(1) if m else name
        # Auto-generated `.formatter` / `.parenthesizer` / `.delaborator`
        # children are registered when the parent is declared. Privatizing
        # the parent makes them inaccessible by their derived name. So if
        # we see any of these suffixes, revert the parent.
        for suffix in (".formatter", ".parenthesizer", ".delaborator"):
            if clean.endswith(suffix):
                clean = clean[: -len(suffix)]
                break
        fqs.add(clean)

    # 1. "must be public"
    for m in re.finditer(
            r"Declaration `([^`]+)` must be public", text):
        add_unprivate(m.group(1))

    # 2. Unknown identifier (Lean uses backticks, not single quotes)
    for m in re.finditer(r"Unknown identifier `([^`]+)`", text):
        add_unprivate(m.group(1))
    # also try the single-quote form just in case
    for m in re.finditer(r"Unknown identifier '([^']+)'", text):
        add_unprivate(m.group(1))

    # 3. Unknown constant
    for m in re.finditer(r"Unknown constant `([^`]+)`", text):
        add_unprivate(m.group(1))

    # 4. private declaration X exists
    for m in re.finditer(
            r"A private declaration `([^`]+)` exists", text):
        add_unprivate(m.group(1))

    # 4a. (kernel) declaration has metavariables 'X.Y.Z'
    # An auto-derived `instMkXxx` instance fails to type-check because one of
    # its components (a private decl we hid) can't be resolved. Revert the
    # named decl AND any decl in the manifest with the same module prefix.
    for m in re.finditer(
            r"\(kernel\) declaration has metavariables '([^']+)'", text):
        add_unprivate(m.group(1))

    # 4b. failed to compile definition, compiler IR check failed at `X`
    for m in re.finditer(
            r"failed to compile definition, compiler IR check failed at `([^`]+)`",
            text):
        add_unprivate(m.group(1))

    # 4c. Failed to rewrite using equation theorems for `X`
    for m in re.finditer(
            r"Failed to rewrite using equation theorems for `([^`]+)`", text):
        add_unprivate(m.group(1))

    # 4d. failed to synthesize <Class> — class instance synthesis failure.
    # Pattern: "failed to synthesize\s*\n\s*ClassName". Extracts the class name.
    for m in re.finditer(
            r"failed to synthesize\s*\n\s*(\S+)(?:\s|$)", text):
        add_unprivate(m.group(1))

    # 4e. unknown projection `X` — struct projection accessor.
    # When a struct field accessor is privatized, field access breaks.
    for m in re.finditer(
            r"unknown projection `([^`]+)`", text):
        add_unprivate(m.group(1))

    # 5. Invalid field
    for m in re.finditer(
            r"Invalid field `([^`]+)`: ", text):
        fqs.add("<<INVALID_FIELD:" + m.group(1) + ">>")

    # 6. Catch-all: file paths in errors that we cannot confidently parse
    # by decl name (parser breakage, unsolved goals, syntax errors, etc.).
    # Map error-file-path → mathlib module name and revert ALL manifest
    # entries from that module.
    bad_patterns = (
        r"unknown parser declaration",
        r"unexpected token .* expected",
        r"don't know how to synthesize placeholder",
        r"unsolved goals",
        r"unknown identifier",
        r"Unknown identifier",  # capitalized form
        r"`fun_prop` was unable to prove",
        r"Tactic `rewrite` failed",
        r"invalid syntax node kind",
        r"Application type mismatch",
        r"`simp` made no progress",
        r"motive is not type correct",
        r"failed to synthesize",  # class synthesis failure (broad trigger)
        r"structure resolution failed",  # struct or class resolution
        r"unknown projection",  # struct field accessor
    )
    for m in re.finditer(
            r"error: (Mathlib/[\w./]+\.lean):\d+:\d+: ", text):
        rel = m.group(1)
        # Check the line includes one of the bad patterns
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        line = text[line_start:line_end]
        if any(re.search(p, line) for p in bad_patterns):
            mod = rel[:-len(".lean")].replace("/", ".")
            revert_modules.add(mod)

    return fqs, revert_modules


def grep_define_site(leaf: str) -> list[str]:
    """Grep mathlib for files that define a decl with this leaf name.
    Returns relative paths like 'Mathlib/Foo/Bar.lean'. Used as a fallback
    when an `Unknown identifier X` error names a leaf that isn't in our
    manifest — we look for files with `def X` / `theorem X` etc. and then
    cross-reference our manifest for entries in the same file."""
    if not leaf or "." in leaf or "(" in leaf:
        return []
    try:
        out = subprocess.run(
            ["grep", "-rl",
             "-E",
             rf"^(\s*@\[[^]]*\]\s*)*(private|protected|noncomputable|meta|partial|unsafe|\s)*(def|theorem|lemma|abbrev) {re.escape(leaf)}\b",
             "Mathlib/"],
            cwd=str(MATHLIB), capture_output=True, text=True, timeout=20,
        )
        return [l.strip() for l in out.stdout.splitlines() if l.strip()]
    except (subprocess.SubprocessError, OSError):
        return []


def revert_row(row: dict, reason: str) -> dict | None:
    """Strip the `private ` prefix from a single manifest row's file:line.

    Returns a revert record if a `private ` prefix was actually removed,
    otherwise None (file missing, line out of range, or already reverted).
    """
    fp = MATHLIB / row["file"]
    if not fp.exists():
        return None
    src = fp.read_text().splitlines(keepends=True)
    line_idx = row["line"] - 1
    if line_idx >= len(src):
        return None
    line = src[line_idx]
    # Strip the FIRST occurrence of `private ` (followed by space)
    new_line = re.sub(r"\bprivate\s+(?=[a-z@])", "", line, count=1)
    if new_line == line:
        return None  # nothing to strip (already reverted maybe)
    src[line_idx] = new_line
    fp.write_text("".join(src))
    return {"fq_name": row["fq_name"], "file": row["file"],
            "line": row["line"], "reason": reason}


def revert_decl(manifest: dict[str, list[dict]], fq: str, reason: str) -> dict | None:
    """Strip the `private ` prefix from the decl(s) in their file(s).
    Returns the first revert record applied, None if nothing was reverted.

    Resolution strategy (in order):
      1. exact fq match in manifest (loops over ALL rows for that fq —
         the same fq can appear multiple times when the same leaf is
         declared under different namespace contexts in one file).
      2. suffix match (`liftRelAux_inr_inr` → `Computation.liftRelAux_inr_inr`)
      3. namespace-prefix fallback (revert siblings under the same parent
         namespace as the unknown name).
      4. grep mathlib for `def <leaf>`/`theorem <leaf>` etc., then revert any
         manifest entry whose file contains the definition (catches
         `@[simps]`-derived names where the parent struct is in our manifest).
    """
    rows = manifest.get(fq)
    if rows:
        results = []
        for row in rows:
            r = revert_row(row, reason)
            if r is not None:
                results.append(r)
        if results:
            return results[0]
        # exact match but everything already reverted — fall through to
        # the more aggressive heuristics in case a sibling is the real
        # culprit.

    # Suffix match
    candidates = [k for k in manifest
                  if k.endswith("." + fq) or k == fq]
    # Drop the exact-match key if we already tried it above
    if rows is not None:
        candidates = [c for c in candidates if c != fq]
    if len(candidates) == 1:
        for row in manifest[candidates[0]]:
            r = revert_row(row, reason + ":suffix")
            if r is not None:
                return r
    elif len(candidates) > 1:
        results = []
        for c in candidates:
            for row in manifest[c]:
                r = revert_row(row, reason + ":suffix-ambig")
                if r is not None:
                    results.append(r)
        if results:
            return results[0]

    # Fallback A: namespace-prefix match. `MeasureTheory.SimpleFunc.map_add`
    # often resolves via `@[simps]` from some parent `MeasureTheory.SimpleFunc.X`
    # in the manifest. Revert every manifest entry whose fq_name shares
    # the longest namespace prefix.
    results = []
    ns_parts = fq.split(".")
    # Try progressively shorter prefixes (most specific first)
    for prefix_len in range(len(ns_parts) - 1, 0, -1):
        prefix = ".".join(ns_parts[:prefix_len]) + "."
        matches = [k for k in manifest if k.startswith(prefix)]
        if matches:
            for fq2 in matches:
                for row in manifest[fq2]:
                    r = revert_row(row, f"ns-prefix:{prefix}<-{fq}")
                    if r is not None:
                        results.append(r)
            if results:
                return results[0]
    # Fallback B: grep mathlib for files defining this leaf, then
    # revert manifest entries from those files.
    leaf = fq.split(".")[-1]
    files = grep_define_site(leaf)
    if not files:
        return None
    seen: set[tuple[str, int]] = set()
    for f in files:
        for fq2, rows2 in manifest.items():
            for row in rows2:
                key = (row["file"], row["line"])
                if row.get("file") == f and key not in seen:
                    r = revert_row(row, f"grep:{leaf}->{f}")
                    if r is not None:
                        results.append(r)
                        seen.add(key)
    return results[0] if results else None


def main():
    if len(sys.argv) < 2:
        print("usage: bulk_revert.py <build-log>", file=sys.stderr)
        sys.exit(1)
    log_path = Path(sys.argv[1])
    if not log_path.exists():
        print(f"log not found: {log_path}", file=sys.stderr)
        sys.exit(1)

    manifest, all_rows = load_manifest()
    print(f"manifest: {len(all_rows)} privatizations "
          f"({len(manifest)} unique fq_names)", file=sys.stderr)

    fqs, revert_modules = parse_errors(log_path)
    print(f"errors flagged: {len(fqs)} fqs + {len(revert_modules)} module-wide",
          file=sys.stderr)
    for fq in sorted(fqs)[:10]:
        print(f"  fq:  {fq}", file=sys.stderr)
    for mod in sorted(revert_modules)[:5]:
        print(f"  mod: {mod}", file=sys.stderr)

    reverts = []
    not_in_manifest = []
    for fq in fqs:
        if fq.startswith("<<INVALID_FIELD:"):
            field = fq[len("<<INVALID_FIELD:"):-2]
            for row in all_rows:
                if row["fq_name"].split(".")[-1] == field:
                    rev = revert_row(row, f"invalid-field:{field}")
                    if rev is not None:
                        reverts.append(rev)
            continue
        rev = revert_decl(manifest, fq, "build error")
        if rev is None:
            not_in_manifest.append(fq)
        else:
            reverts.append(rev)

    # Module-wide reverts: revert every manifest entry from these modules.
    # Iterate `all_rows` (not `manifest.items()`) so duplicate-fq rows aren't
    # silently skipped — `manifest` is keyed by fq_name and a single fq can
    # have multiple rows.
    for mod in revert_modules:
        for row in all_rows:
            if row.get("module") == mod:
                rev = revert_row(row, f"module-wide:{mod}")
                if rev is not None:
                    reverts.append(rev)

    print(f"reverted: {len(reverts)}", file=sys.stderr)
    print(f"not in manifest: {len(not_in_manifest)}", file=sys.stderr)
    for fq in not_in_manifest[:5]:
        print(f"  not-found: {fq}", file=sys.stderr)

    # Append reverts to the log file
    with REVERTS.open("a") as f:
        for r in reverts:
            f.write(json.dumps(r) + "\n")

    return 0 if reverts else 1


if __name__ == "__main__":
    sys.exit(main())
