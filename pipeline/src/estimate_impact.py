#!/usr/bin/env python3
"""estimate_impact.py — quantify build-CP savings for the 23 chore/privatize-* branches.

Methodology
-----------
The cache-cut lever (PR-38702 shape, validated empirically in §2 of
MAINTAINER_REPORT.md) means:

  edit to the BODY of a `private` decl
    ⇒ M.olean.hash byte-identical
    ⇒ downstream cache-hits across blast(M) — zero re-elaboration

Savings per historical commit C that edited module M:

  (1) C is a "private-body-only edit"
        ⇒ savings = blast_cp_s(M)         (full cone skipped)
  (2) C touches public surface as well
        ⇒ savings = 0                     (cone rebuilds anyway)

We can compute blast_cp_s(M) exactly from the dependency graph. The
historical-edit attribution (1 vs 2) requires looking at each commit's
diff for M. We compute three estimates:

  * UB   = upper bound, assuming every M-edit could have been private-body-only.
           = edits(M) × blast_cp_s(M)

  * PROP = proportional: scale UB by (privatized_lines / module_lines_today).
           Approximates "edits are uniformly distributed across the module".

  * ATTR = per-commit attribution by diff-line analysis. For each historical
           commit C touching M, we extract the line ranges that C modified in M
           and check whether they fall inside any privatized-decl's body span
           (def line ↦ next decl-keyword line). If ALL hunks fall inside, the
           commit is private-body-only and counts toward savings; otherwise 0.
           Body-spans are computed against the file at HEAD on the chore branch
           — i.e., the file as the privatization PR would commit it. This
           biases toward UB if files have churned heavily but is the closest
           we can get without a deeper history-aware decl-tracker.

The total estimate is the sum across all 23 branches.

The unit "blast_cp_s" = critical-path compile-CP-seconds (wall-clock with
infinite parallelism, matching the existing churn_blast pipeline). To
ground the magnitude: lakeprof's reference run is ~1500 CP-s total, so a
savings of N CP-s corresponds to N/1500 ≈ N×0.07 % of one full mathlib
critical-path-elaboration.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

import networkx as nx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

MLB = paths.MATHLIB
GRAPH_GZ = paths.DATA / "lakeprof.graph.json.gz"
GRAPH = paths.DATA / "lakeprof.graph.json"
CHURN = paths.CHURN_BLAST

# How many historical commits to walk. Match the existing pipeline's window.
N_COMMITS = 1500


def load_graph() -> nx.DiGraph:
    """Load the dependency graph; return a DiGraph with `time` on each node.

    Accepts either `lakeprof.graph.json` (plain) or `lakeprof.graph.json.gz`
    (the form shipped in the repo, ~600 KB vs ~9 MB).
    """
    import gzip
    if GRAPH.exists():
        data = json.loads(GRAPH.read_text())
    elif GRAPH_GZ.exists():
        with gzip.open(GRAPH_GZ, "rb") as f:
            data = json.loads(f.read().decode("utf-8"))
    else:
        raise FileNotFoundError(f"neither {GRAPH} nor {GRAPH_GZ} exists")
    g = nx.DiGraph()
    for n in data["nodes"]:
        g.add_node(n["id"], time=n.get("time", 0.0))
    for e in data["edges"]:
        g.add_edge(e["source"], e["target"])
    return g


def blast_cp_for(module: str, g: nx.DiGraph) -> tuple[float, int]:
    """Return (critical-path-CP of the blast cone of `module`, count of
    ancestors).

    Matches the existing churn_blast pipeline's definition: critical path
    via networkx.dag_longest_path on the subgraph of (ancestors ∪ {module}),
    weighted by node `time`. This represents wall-clock seconds the
    rebuild would take with infinite parallelism — not total CPU-seconds.
    """
    if module not in g.nodes:
        return (0.0, 0)
    anc = nx.ancestors(g, module)
    affected = anc | {module}
    if not affected:
        return (0.0, 0)
    sub = g.subgraph(affected).copy()
    # The graph's edge weights default to 0; we want each edge to carry
    # the SOURCE node's time so that dag_longest_path sums per-node times
    # along the path. (This matches p07_churn_blast.py.)
    for u, _, d in sub.edges(data=True):
        d["time"] = sub.nodes[u]["time"]
    try:
        path = nx.dag_longest_path(sub, weight="time")
        cp = sum(sub.nodes[u]["time"] for u in path)
    except Exception:
        cp = 0.0
    return (cp, len(anc))


def path_to_module(path: str) -> str | None:
    """Mathlib/Foo/Bar.lean ↦ Mathlib.Foo.Bar"""
    if not path.startswith("Mathlib/") or not path.endswith(".lean"):
        return None
    return path[: -len(".lean")].replace("/", ".")


def per_module_edits(n: int) -> dict[str, int]:
    """Walk last n commits on master and count edits per Mathlib module."""
    log = subprocess.check_output(
        ["git", "-C", str(MLB), "log", "master", f"-n{n}",
         "--pretty=format:%H", "--name-only", "--no-merges"],
        text=True,
    ).strip().split("\n\n")
    edits: dict[str, int] = defaultdict(int)
    for entry in log:
        lines = entry.split("\n")
        if not lines:
            continue
        for path in lines[1:]:
            m = path_to_module(path)
            if m:
                edits[m] += 1
    return edits


# ---- per-branch attribution helpers ----

DECL_HEADER = re.compile(
    r"^(?:private\s+|protected\s+|noncomputable\s+|partial\s+|unsafe\s+|@\[[^\]]*\]\s*)*"
    r"(?:def|theorem|lemma|abbrev|instance|structure|class|inductive|example|"
    r"axiom|opaque|notation|syntax|elab|macro|attribute|initialize|namespace|"
    r"end|section|variable|open|import|set_option)\b"
)


def parse_privatized_decls_from_diff(diff_text: str) -> list[tuple[str, str]]:
    """For a `git diff master <branch>` output, identify each decl whose `def`
    line gained the `private` prefix.

    Returns list of (filepath, leaf-name) pairs.
    """
    out = []
    cur_file = None
    for line in diff_text.split("\n"):
        if line.startswith("+++ b/"):
            cur_file = line[len("+++ b/"):].strip()
            continue
        if not line.startswith("+"):
            continue
        body = line[1:]
        m = re.match(
            r"^private\s+(?:partial\s+)?def\s+([^\s\(\[\:]+)",
            body,
        )
        if m and cur_file:
            out.append((cur_file, m.group(1)))
    return out


def find_decl_body_span(file_lines: list[str], leaf: str) -> tuple[int, int] | None:
    """Locate `private (partial )?def <leaf>` in the file and return its
    body span as a (start_line, end_line_exclusive) 1-indexed range.

    The body extends from the def-line (inclusive) until the next decl-header
    line at the same indentation depth (or EOF). This is a heuristic — Lean's
    real decl boundaries are more nuanced (terminating `where`/`with`
    blocks, mutual recursion, etc.) — but it's good enough for line-overlap
    intersection tests. We bias toward over-counting body lines (treats the
    span as larger than reality), which makes ATTR an *upper* estimate of
    private-body-only commits.
    """
    pat = re.compile(
        rf"^private\s+(?:partial\s+)?def\s+{re.escape(leaf)}(?:\s|\(|\[|:|$)"
    )
    start = None
    for i, ln in enumerate(file_lines, start=1):
        if pat.match(ln):
            start = i
            break
    if start is None:
        return None
    # Walk forward to find the next top-level decl header.
    end = len(file_lines) + 1
    for j in range(start + 1, len(file_lines) + 1):
        ln = file_lines[j - 1]
        if DECL_HEADER.match(ln):
            end = j
            break
    return (start, end)


def diff_hunks_for(branch_name: str, module_path: str, in_window: list[str]) -> dict[str, list[tuple[int, int]]]:
    """For each commit sha in in_window that touched module_path, return the
    list of (start_line_in_old_file, line_count_modified) intervals from the
    diff. We use the OLD-FILE line numbers because we want to know "what
    region was touched" relative to the historical state.

    Implementation: parse `git log -p <sha>^..<sha> -- <module_path>`. We
    only care about the @@ -<start>,<count>... headers in the diff hunks.
    """
    if not in_window:
        return {}
    # Use one big git log call rather than one per sha (much faster)
    sha_args = ["git", "-C", str(MLB), "log",
                "--pretty=format:===%H", "-p", "--no-merges", "--unified=0",
                "--"]
    # Bound history to window — restrict by sha list via git log master -n N
    # Implementation detail: simpler to do `git log master -n 1500 -- <path>`
    cmd = ["git", "-C", str(MLB), "log", "master", f"-n{N_COMMITS}",
           "--pretty=format:===%H", "-p", "--no-merges", "--unified=0",
           "--", module_path]
    raw = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
    hunks_by_sha: dict[str, list[tuple[int, int]]] = defaultdict(list)
    cur_sha = None
    for line in raw.split("\n"):
        if line.startswith("==="):
            cur_sha = line[3:].strip()
            continue
        # Hunk header: @@ -<from>,<n> +<to>,<m> @@
        m = re.match(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line)
        if m and cur_sha:
            from_start = int(m.group(1))
            from_n = int(m.group(2)) if m.group(2) else 1
            if from_n == 0:
                # Pure addition — anchor is the line AFTER from_start in the OLD file,
                # but for our overlap test we treat additions as "next to" from_start.
                hunks_by_sha[cur_sha].append((from_start, 1))
            else:
                hunks_by_sha[cur_sha].append((from_start, from_n))
    return hunks_by_sha


def count_in_window(module_path: str) -> tuple[int, list[str]]:
    """Return (count, list of shas) of historical commits in last N_COMMITS
    that touched module_path."""
    cmd = ["git", "-C", str(MLB), "log", "master", f"-n{N_COMMITS}",
           "--pretty=format:%H", "--no-merges", "--", module_path]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=60).stdout
    shas = [s for s in out.strip().split("\n") if s]
    return (len(shas), shas)


def overlaps_any(hunk_ranges: list[tuple[int, int]],
                 body_spans: list[tuple[int, int]]) -> tuple[bool, bool]:
    """Given hunk_ranges = [(start, count), ...] in the OLD file and
    body_spans = [(start_inclusive, end_exclusive), ...] in the CURRENT file:
    return (any_overlap, all_overlap_is_with_body_spans).

    NOTE: comparing OLD-file line numbers to CURRENT-file body spans is
    imprecise (lines drift). For modules with low churn this is fine; for
    high-churn modules, ATTR may over- or under-count. We treat it as a
    rough estimate, not authoritative.
    """
    if not hunk_ranges:
        return (False, True)  # vacuous
    any_in = False
    all_in = True
    for hs, hn in hunk_ranges:
        he = hs + hn
        in_body = False
        for bs, be in body_spans:
            if hs < be and bs < he:
                in_body = True
                break
        if in_body:
            any_in = True
        else:
            all_in = False
    return (any_in, all_in)


def estimate_branch(branch: str, g: nx.DiGraph) -> dict:
    """Compute UB, PROP, and ATTR savings for one branch."""
    diff = subprocess.run(
        ["git", "-C", str(MLB), "diff", "master", branch],
        capture_output=True, text=True,
    ).stdout
    privatized = parse_privatized_decls_from_diff(diff)
    if not privatized:
        return {"branch": branch, "error": "no privatized decls found"}

    # All decls in this branch belong to one file (by our PR design)
    files = {f for f, _ in privatized}
    if len(files) > 1:
        return {"branch": branch, "error": f"multi-file branch: {files}"}
    file_path = next(iter(files))
    module = path_to_module(file_path)

    # Blast cone CP
    blast_cp, blast_n = blast_cp_for(module, g)

    # Edits in window touching this file
    edit_count, shas = count_in_window(file_path)

    # Read the file at the chore branch's tip to compute body spans
    file_at_branch = subprocess.run(
        ["git", "-C", str(MLB), "show", f"{branch}:{file_path}"],
        capture_output=True, text=True,
    ).stdout.split("\n")
    total_lines = len(file_at_branch)

    body_spans = []
    for _, leaf in privatized:
        span = find_decl_body_span(file_at_branch, leaf)
        if span:
            body_spans.append(span)
    privatized_lines = sum(be - bs for bs, be in body_spans)
    prop_factor = privatized_lines / total_lines if total_lines else 0.0

    # Per-commit attribution
    hunks_by_sha = diff_hunks_for(branch, file_path, shas)
    attr_savable_commits = 0
    for sha in shas:
        hunks = hunks_by_sha.get(sha, [])
        if not hunks:
            # Commit touched the file but the diff was empty against master — odd.
            # Conservative: treat as unsavable.
            continue
        any_in, all_in = overlaps_any(hunks, body_spans)
        if all_in and any_in:
            attr_savable_commits += 1

    return {
        "branch": branch,
        "module": module,
        "n_privatized": len(privatized),
        "blast_cp_s": blast_cp,
        "blast_cone_size": blast_n,
        "edits_in_window": edit_count,
        "module_lines": total_lines,
        "privatized_lines": privatized_lines,
        "prop_factor": prop_factor,
        "attr_savable_commits": attr_savable_commits,
        "ub_cp_s": edit_count * blast_cp,
        "prop_cp_s": edit_count * blast_cp * prop_factor,
        "attr_cp_s": attr_savable_commits * blast_cp,
    }


def main():
    print(f"loading dep graph from {GRAPH.name}...")
    g = load_graph()
    print(f"  {g.number_of_nodes():,} nodes, {g.number_of_edges():,} edges")

    branches = subprocess.run(
        ["git", "-C", str(MLB), "branch", "--list", "chore/privatize-*"],
        capture_output=True, text=True,
    ).stdout.strip().splitlines()
    branches = [b.strip("* ").strip() for b in branches]
    print(f"  {len(branches)} chore/privatize-* branches")
    print()

    rows = []
    for b in branches:
        r = estimate_branch(b, g)
        rows.append(r)
        if "error" in r:
            print(f"✖ {b}: {r['error']}")
            continue
        print(f"  {b}")
        print(f"    module={r['module']}")
        print(f"    blast_cp={r['blast_cp_s']:.1f} CP-s ({r['blast_cone_size']} ancestors)")
        print(f"    edits={r['edits_in_window']}, attr_savable={r['attr_savable_commits']}, "
              f"prop_factor={r['prop_factor']:.3f}")
        print(f"    UB={r['ub_cp_s']:.1f}, PROP={r['prop_cp_s']:.1f}, ATTR={r['attr_cp_s']:.1f}  CP-s")

    valid = [r for r in rows if "error" not in r]
    ub_total = sum(r["ub_cp_s"] for r in valid)
    prop_total = sum(r["prop_cp_s"] for r in valid)
    attr_total = sum(r["attr_cp_s"] for r in valid)
    edits_total = sum(r["edits_in_window"] for r in valid)
    attr_total_commits = sum(r["attr_savable_commits"] for r in valid)
    print()
    print("=" * 70)
    print(f"Window: last {N_COMMITS} commits on mathlib master")
    print(f"Branches accounted for: {len(valid)} / {len(rows)}")
    print()
    print(f"  Edits in window touching the 23 modules:    {edits_total}")
    print(f"  Of those, attributed to private bodies:     {attr_total_commits} "
          f"({100*attr_total_commits/max(edits_total,1):.1f}%)")
    print()
    print("  Cumulative CP-seconds saved over the window:")
    print(f"    Upper bound  (all edits hit only private bodies)  {ub_total:>9.1f}")
    print(f"    Proportional (private_lines / module_lines)       {prop_total:>9.1f}")
    print(f"    Attributed   (per-commit diff intersection)       {attr_total:>9.1f}")
    print()
    # Reference: 1 CP-s = "one second of compute on the critical path"
    # For scaling: full mathlib critical-path build ≈ 1500 CP-s in lakeprof.
    full_build = 1500.0
    n_full_avoided = attr_total / full_build
    print(f"  Reference: full mathlib build ≈ {full_build:.0f} CP-s")
    print(f"  ATTR savings ≈ {n_full_avoided:.2f} full-mathlib-builds saved over the window")
    print(f"  Per-commit average (window={N_COMMITS}): {attr_total/N_COMMITS:.2f} CP-s/commit")

    out_path = ROOT / "experiments" / "hide-decls" / "pr1" / "estimated_impact.json"
    out_path.write_text(json.dumps({
        "n_commits_window": N_COMMITS,
        "branches": rows,
        "totals": {
            "edits": edits_total,
            "attr_savable_commits": attr_total_commits,
            "ub_cp_s": ub_total,
            "prop_cp_s": prop_total,
            "attr_cp_s": attr_total,
        },
    }, indent=2))
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    main()
