#!/usr/bin/env python3
"""bulk_no_expose_revert.py — parse a `lake build` log and remove the
`@[no_expose]` lines that broke the build.

Companion to bulk_no_expose_apply.py / bulk_no_expose_iterate.sh. The apply
script wrote a manifest mapping each inserted `@[no_expose]` to its file +
line; this script reads build errors, identifies which decls were the cause,
removes the matching attribute line, and rewrites the manifest with the
remaining live entries.

Error patterns recognized (most specific first):
  P1. `Compilation failed, locally inferred compilation type differs ...
       Some of the following definitions may need to be `@[expose]`'d to fix
       this mismatch: NAME ↦ N`
       → revert NAME directly.
  P2. `Invalid field `X`: The environment does not contain `Y.X``
       → revert X (the field). Look it up by leaf name in the same module.
  P3. `Invalid pattern: Expected a constructor or constant marked with
       `[match_pattern]``
       → revert the most recent @[no_expose] in the failing module's file.
       (Coarse, but pattern errors don't name the culprit.)
  P4. `Invalid rewrite argument: Expected an equality or iff proof or
       definition name, but X is a value of type ...`
       → revert X.
  P5. Generic / unmatched failure in module M
       → revert the most recent @[no_expose] in M's file (one per iteration).

The script always makes progress: if no specific revert candidate is found
for any error, the most recent @[no_expose] in each failing file is removed.

Output (stdout):
  reverted: N
  details: list of (file, decl_name) lines

Exit code: 0 if at least one revert happened, 1 if nothing to revert.
"""
from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

MATHLIB = paths.MATHLIB
WORK = paths.DATA / "work" / "no_expose"
MANIFEST = WORK / "manifest.jsonl"
REVERTED = WORK / "reverted.jsonl"


def load_manifest() -> list[dict]:
    if not MANIFEST.exists():
        return []
    return [json.loads(l) for l in MANIFEST.read_text().splitlines() if l.strip()]


def parse_errors(log_text: str) -> tuple[set[str], set[str], list[tuple[str, int]]]:
    """Return (decl-names-to-revert, failing-files, [(file, line) per error]).
    The first set: specific decl names found in error messages.
    The second set: file paths that had any error.
    The list: each individual error site (PATH:LINE), used to revert by proximity.
    """
    decls: set[str] = set()
    files: set[str] = set()
    sites: list[tuple[str, int]] = []

    # P1: locally inferred type differs, names the decls
    for m in re.finditer(
        r"Some of the following definitions may need to be `@\[expose\]`'d.*?:\s*([^\n]+)",
        log_text, re.DOTALL,
    ):
        chunk = m.group(1)
        # Format is "NAME ↦ N" possibly with multiple
        for nm in re.finditer(r"([A-Za-z_][\w.]*)\s*↦", chunk):
            decls.add(nm.group(1).split(".")[-1])

    # P2: Invalid field
    for m in re.finditer(r"Invalid field `(\w+)`", log_text):
        decls.add(m.group(1))

    # P4: Invalid rewrite argument (less reliable pattern)
    for m in re.finditer(r"Invalid rewrite argument:.*?but\s+`?(\w+)", log_text):
        decls.add(m.group(1))

    # Unknown constants — sometimes downstream issue. The name class includes
    # apostrophe/prime/superscript chars that mathlib uses; broaden beyond \w.
    NAME_CLASS = r"[\w.«»'!?₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹]+"
    for m in re.finditer(r"Unknown constant `(" + NAME_CLASS + r")`", log_text):
        nm = m.group(1).split(".")[-1]
        # Filter out built-in / Lean-internal names
        if not nm.startswith("_"):
            decls.add(nm)

    # Failing files + per-error sites (from error: PATH:LINE:COL: ... lines)
    for m in re.finditer(r"^error:\s+([^\s:]+\.lean):(\d+):", log_text, re.MULTILINE):
        files.add(m.group(1))
        sites.append((m.group(1), int(m.group(2))))
    # Also "trace:" lines that have the file
    for m in re.finditer(r"^Some required targets logged failures:\s*\n((?:- .+\n?)+)", log_text, re.MULTILINE):
        for fm in re.finditer(r"^- ([\w.]+)$", m.group(1), re.MULTILINE):
            mod = fm.group(1)
            files.add(mod.replace(".", "/") + ".lean")

    return decls, files, sites


def revert_entry(entry: dict) -> bool:
    """Revert one manifest entry by searching the file for the decl name.

    More robust than relying on the manifest's `line_inserted_at`, which
    drifts as cumulative inserts shift line numbers.

    For action=no_expose: find the `@[no_expose]` line directly above the
    decl's `def NAME ...` header (possibly past modifier lines) and delete it.
    For action=private: find the line `private (noncomputable )? (def|theorem|lemma) NAME ...`
    and strip the leading `private `.
    """
    file_rel = entry["file"]
    action = entry.get("action", "no_expose")
    name = entry["decl_name"]
    path = MATHLIB / file_rel
    if not path.exists():
        return False
    lines = path.read_text().splitlines(keepends=True)

    # Find the decl line. Match `(private )? (noncomputable )? (def|theorem|lemma) <FULL_NAME>`
    # where FULL_NAME ends in `.<name>` or `<name>` — handles dotted source forms
    # like `theorem Disjoint.symmDiff_eq_sup` where the manifest only has the leaf.
    # Sort.lean and similar files reuse the same leaf name across multiple namespaces;
    # for action=private we specifically want the one currently carrying `private `,
    # because earlier reverts may have already cleared other occurrences.
    head_re = re.compile(
        r"^(?P<indent>\s*)"
        r"(?P<attrs>(?:@\[[^\]]*\]\s*)*)"  # inline @[…] attributes BEFORE `private`
        r"(?P<priv>private\s+)?"
        r"(?:noncomputable\s+|partial\s+|unsafe\s+|protected\s+)*"
        r"(?P<kw>def|theorem|lemma)\s+"
        r"(?P<full>[\w.«»'!?₀₁₂₃₄₅₆₇₈₉⁰¹²³⁴⁵⁶⁷⁸⁹]+)"
    )
    matches: list[tuple[int, re.Match]] = []
    for i, line in enumerate(lines):
        m = head_re.match(line)
        if m and (m.group("full") == name or m.group("full").endswith("." + name)):
            matches.append((i, m))
    if not matches:
        return False
    # For private actions, prefer the match that still has `private` prefix.
    # For no_expose actions, prefer the match that has `@[no_expose]` directly above.
    decl_idx = None
    decl_match = None
    if action == "private":
        for i, m in matches:
            if m.group("priv"):
                decl_idx, decl_match = i, m; break
    else:  # no_expose
        for i, m in matches:
            j = i - 1
            while j >= 0:
                stripped = lines[j].strip()
                if "@[no_expose]" in lines[j]:
                    decl_idx, decl_match = i, m; break
                if (stripped in {"noncomputable", "partial", "unsafe", "protected"}
                    or stripped.startswith("@[")
                    or (stripped.startswith("set_option") and stripped.endswith(" in"))):
                    j -= 1; continue
                break
            if decl_idx is not None:
                break
    # Fallback to the first occurrence even if it doesn't match the action.
    # (Caller-side `manifest[idx] = None` should still happen so the entry
    # doesn't loop forever.)
    if decl_idx is None:
        return False

    if action == "no_expose":
        # Walk back over modifier/attribute lines and find the `@[no_expose]` line
        j = decl_idx - 1
        while j >= 0:
            stripped = lines[j].strip()
            if "@[no_expose]" in lines[j]:
                del lines[j]
                path.write_text("".join(lines))
                return True
            if (stripped in {"noncomputable", "partial", "unsafe", "protected"}
                or stripped.startswith("@[")
                or (stripped.startswith("set_option") and stripped.endswith(" in"))):
                j -= 1
                continue
            break
        return False
    elif action == "private":
        # Strip the `private ` token from the decl line, wherever it appears
        # after the inline attribute prefix.
        m = head_re.match(lines[decl_idx])
        if not m or not m.group("priv"):
            return False
        line = lines[decl_idx]
        # Remove the first `private ` token. May appear right after indent
        # or right after an inline `@[…] ` attribute group.
        line = re.sub(r"private\s+", "", line, count=1)
        lines[decl_idx] = line
        path.write_text("".join(lines))
        return True
    return False


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: bulk_no_expose_revert.py <build-log>", file=sys.stderr)
        return 2
    log_text = Path(sys.argv[1]).read_text()
    decls, files, sites = parse_errors(log_text)
    print(f"parsed: {len(decls)} decl names, {len(files)} failing files, "
          f"{len(sites)} error sites", file=sys.stderr)

    manifest = load_manifest()
    if not manifest:
        print("reverted: 0")
        print("no manifest — nothing to revert")
        return 1

    by_decl: dict[str, list[int]] = defaultdict(list)  # decl_name -> manifest indices
    by_file: dict[str, list[int]] = defaultdict(list)  # file -> manifest indices (ascending line)
    for idx, m in enumerate(manifest):
        by_decl[m["decl_name"]].append(idx)
        by_file[m["file"]].append(idx)

    to_revert: set[int] = set()
    # Direct decl-name matches — revert those entries.
    for name in decls:
        for idx in by_decl.get(name, []):
            to_revert.add(idx)
    # Site-proximity revert: for each (file, line) error site, revert manifest
    # entries in that file whose line_inserted_at is within a ±10 line window.
    WINDOW = 10
    for fpath, err_line in sites:
        for key in by_file:
            if not (key.endswith(fpath) or fpath.endswith(key)):
                continue
            for idx in by_file[key]:
                if abs(manifest[idx]["line_inserted_at"] - err_line) <= WINDOW:
                    to_revert.add(idx)
            break
    # Whole-file revert: for every failing file, revert all manifest entries
    # in that file. Cross-file semantic-error cascades (e.g. `Not a definitional
    # equality`) don't name a single culprit, so the only reliable way to
    # converge is to drop the entire file's worth of edits and let the next
    # iteration find a residue that builds.
    for fpath in files:
        for key in by_file:
            if not (key.endswith(fpath) or fpath.endswith(key)):
                continue
            for idx in by_file[key]:
                to_revert.add(idx)
            break

    if not to_revert:
        print("reverted: 0")
        return 1

    # Sort by (file, line) descending so removals don't shift earlier lines in same file
    by_file_for_revert: dict[str, list[int]] = defaultdict(list)
    for idx in to_revert:
        by_file_for_revert[manifest[idx]["file"]].append(idx)
    for f, idxs in by_file_for_revert.items():
        idxs.sort(key=lambda i: -manifest[i]["line_inserted_at"])

    reverted_log = REVERTED.open("a") if REVERTED.exists() else REVERTED.open("w")
    actually_reverted = 0
    skipped_stale = 0
    for fpath, idxs in by_file_for_revert.items():
        for idx in idxs:
            m = manifest[idx]
            if revert_entry(m):
                reverted_log.write(json.dumps(m) + "\n")
                manifest[idx] = None  # mark dead
                actually_reverted += 1
                # Adjust line_inserted_at for other entries in same file
                # if the revert removed a line (action=no_expose only).
                if m.get("action", "no_expose") == "no_expose":
                    for k_idx in range(len(manifest)):
                        if (manifest[k_idx] is not None
                            and manifest[k_idx]["file"] == m["file"]
                            and manifest[k_idx]["line_inserted_at"] > m["line_inserted_at"]):
                            manifest[k_idx]["line_inserted_at"] -= 1
            else:
                # The decl is no longer findable in the file (probably already
                # reverted in a prior pass under a different name or shifted
                # off). Still mark it dead so we don't loop forever trying.
                manifest[idx] = None
                skipped_stale += 1
    reverted_log.close()
    if skipped_stale:
        print(f"stale-marked: {skipped_stale}", file=sys.stderr)

    # Also adjust line offsets globally for remaining manifest entries in same files
    # whose line is greater than removed lines.  We did per-file pass above; we
    # need to apply removals to entries that weren't in to_revert.
    # Build (file, removed_line) pairs from reverted_log just written.
    # For simplicity, re-read the file and infer.  (The next iterate-pass will re-scan
    # anyway, so any drift only matters if multiple reverts in same file occur.)

    # Write back manifest minus reverted
    MANIFEST.write_text("".join(json.dumps(m) + "\n" for m in manifest if m is not None))
    print(f"reverted: {actually_reverted}")
    return 0 if actually_reverted > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
