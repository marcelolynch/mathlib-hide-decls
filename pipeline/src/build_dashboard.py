#!/usr/bin/env python3
"""build_dashboard.py — generate a single-file HTML dashboard from the
mathlib privatization candidate pipeline.

Inputs (defaults, overridable via flags):
  - experiments/hide-decls/out/census_lean.jsonl
  - experiments/hide-decls/out/ranked_candidates_lean.jsonl
  - pipeline/out/churn_blast.json
  - experiments/hide-decls/dashboard/tracking_state.json (state file, optional)
  - experiments/hide-decls/pr1/estimated_impact.json (optional)

Outputs:
  - experiments/hide-decls/dashboard/index.html  — the single-file dashboard
  - experiments/hide-decls/dashboard/tracking_state.json  — updated state

Run periodically (e.g., after each fresh census run). Diff in the state file
shows what moved between runs (candidate→merged, new candidates, etc.).

The dashboard is one HTML file with embedded CSS+JS, no external dependencies.
Tables are sortable, searchable, and link directly to the relevant module
file in mathlib4 source.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from collections import Counter, defaultdict
from html import escape as h
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import paths  # noqa: E402

CENSUS = paths.CENSUS                  # accepts .gz via paths.open_jsonl
RANKED = paths.RANKED
CHURN = paths.CHURN_BLAST
IMPACT = paths.ESTIMATED_IMPACT
STATE = paths.DATA / "dashboard_state.json"
OUT_HTML = paths.REPO / "site" / "index.html"


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_jsonl(path: Path) -> list[dict]:
    """Load a JSONL file (gzipped or plain) into a list of dicts.

    Uses `paths.open_jsonl` so the same path can refer to either
    `foo.jsonl` or `foo.jsonl.gz`. Returns [] if neither exists, so the
    dashboard still renders against missing optional inputs (e.g. when
    a fresh checkout has not run the census yet).
    """
    try:
        f = paths.open_jsonl(path)
    except FileNotFoundError:
        return []
    rows: list[dict] = []
    with f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def load_state(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text())
    return {"runs": [], "decls": {}}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # `runs` array stays pretty (small + readable); `decls` map is one
    # compact line per entry — readable on diff but ~3× smaller than indent=2
    runs_json = json.dumps(state.get("runs", []), indent=2)
    decl_lines = []
    for fq, info in sorted(state.get("decls", {}).items()):
        decl_lines.append(f"    {json.dumps(fq)}: {json.dumps(info, separators=(',', ':'))}")
    decls_block = "{\n" + ",\n".join(decl_lines) + "\n  }" if decl_lines else "{}"
    path.write_text(f'{{\n  "runs": {runs_json},\n  "decls": {decls_block}\n}}\n')


# ---------------------------------------------------------------------------
# Annotation helpers — produce per-candidate "why" / "why not" remarks.
# ---------------------------------------------------------------------------

# Load policy from the shared loader (same directory).
import policy as _policy  # noqa: E402

NEVER_HIDE_KINDS = _policy.never_hide_kinds()
INTERNAL_PATTERNS = set(_policy.tier_1().get("intent_safe_theorem_patterns", []))
FORBIDDEN_NAME_PATTERNS = _policy.forbidden_name_patterns()


def explain_decl(r: dict, top30: set[str]) -> tuple[str, list[str], list[str]]:
    """Return (verdict, positive_signals, negative_signals) for a single decl row.

    verdict ∈ {"tier1", "tier3", "blocked-private", "blocked-attr", "blocked-kind",
                "blocked-noncandidate", "blocked-theorem-public",
                "blocked-synth-aux", "blocked-name-pattern", "blocked-meta-consumer"}
    """
    pos, neg = [], []

    # ---- Hard blocks (the decl will never be a candidate) ----
    if r.get("is_private"):
        neg.append("Already <code>private</code>")
        return "blocked-private", pos, neg

    kind = r.get("kind", "?")
    if kind in NEVER_HIDE_KINDS:
        neg.append(f"<code>kind={kind}</code>: never auto-hide (parent type, class, or recursor)")
        return "blocked-kind", pos, neg

    fq = r.get("fq_name", "")
    if _policy.is_synthesized_aux(fq):
        neg.append("Elaborator-synthesized name (auto-generated)")
        return "blocked-synth-aux", pos, neg

    pattern = r.get("name_pattern", "normal")
    if pattern in FORBIDDEN_NAME_PATTERNS:
        if pattern == "simps_projection":
            simps_parent = r.get("simps_parent")
            extra = (f", parent <code>{h(simps_parent)}</code>"
                     if simps_parent else "")
            neg.append(
                "<code>name_pattern=simps_projection</code>: namespace ends in "
                "<code>.Simps</code>; consumed by <code>@[simps]</code>-derived "
                f"lemmas in arbitrary modules{extra}. Term-graph references do "
                "not capture meta-time lookups.")
        else:
            neg.append(f"<code>name_pattern={pattern}</code> listed in policy.toml's "
                       f"forbidden_name_patterns")
        return "blocked-name-pattern", pos, neg

    if r.get("forbidden_attrs"):
        attrs = r["forbidden_attrs"]
        neg.append(f"Has forbidden attribute(s): <code>@[{', '.join(attrs)}]</code>")
        return "blocked-attr", pos, neg

    # `meta_consumers` is populated by the extension-aware census pass
    # (DeclCensus.lean's buildMetaConsumersMap). If a decl is registered in
    # any extension's by-name registry (e.g. `@[simps]`), privatizing it
    # would break the extension's lookups — mark as blocked.
    meta = r.get("meta_consumers") or []
    if meta:
        neg.append(
            f"Registered in extension(s): <code>"
            f"{', '.join('@[' + h(m) + ']' for m in meta)}</code>. "
            "Extension looks up the decl by name at meta-time; "
            "privatizing breaks that lookup.")
        return "blocked-meta-consumer", pos, neg

    # ---- Soft blocks (the decl is in a category that requires extra scrutiny) ----
    has_doc = r.get("has_docstring", False)
    # `pattern` was read above for the hard-block check; reuse it here.
    if kind in {"theorem", "lemma"}:
        if has_doc and pattern == "normal":
            neg.append(
                "Theorem with docstring and <code>name_pattern=normal</code>; "
                "treated as public API.")
            return "blocked-theorem-public", pos, neg
        if has_doc:
            neg.append(
                "Theorem has docstring (treated as public API) but "
                f"<code>name_pattern={pattern}</code>.")
        if pattern == "normal":
            neg.append(
                "Theorem without docstring and <code>name_pattern=normal</code>: "
                "no internal-intent signal.")

    # ---- External user / intra-module checks ----
    n_ext = r.get("n_external_users", 0)
    n_intra = r.get("n_intra_module_refs", 0)
    n_sig = r.get("n_signature_refs", 0)

    # ---- Tier-3 hub candidate? ----
    if kind in {"def", "abbrev"} and n_sig >= 5 and n_ext <= 30:
        pos.append(f"Hub-shaped: <b>{n_sig}</b> same-module decls reference it in their type.")
        if n_ext == 0:
            pos.append("<b>0 external users</b>: self-contained cluster.")
        elif n_ext <= 5:
            pos.append(f"<b>{n_ext}</b> external user(s); finite refactor cost.")
        else:
            pos.append(f"<b>{n_ext}</b> external users; needs sub-module extraction.")
        # Could also be tier-1; check below

    # ---- Tier-1 candidate? (mech-hidable + intent-safe) ----
    # Mech-hidable: n_external_users == 0 AND n_signature_refs == 0.
    # Body refs (n_intra_module_refs - n_signature_refs) do not constrain
    # privatization because private decls remain visible inside their
    # defining module, so proofs that reference the hub continue to type-check.
    if n_ext == 0 and n_sig == 0:
        body_refs = n_intra
        if body_refs == 0:
            pos.append("<b>0 external users</b>, <b>0 intra-module refs</b>: mechanically safe.")
        else:
            pos.append(f"<b>0 external users</b>, <b>0 signature refs</b>"
                       f" ({body_refs} body ref{'s' if body_refs != 1 else ''}, "
                       f"which don't constrain privatization): mechanically safe.")
        if kind in {"def", "abbrev"}:
            pos.append(f"<code>kind={kind}</code>: defs and abbrevs hide freely.")
            verdict = "tier1"
        elif kind in {"theorem", "lemma"} and not has_doc and pattern in INTERNAL_PATTERNS:
            pos.append(f"Theorem flagged internal: no docstring, <code>pattern={pattern}</code>.")
            verdict = "tier1"
        else:
            verdict = "blocked-noncandidate"
            if kind in {"theorem", "lemma"}:
                neg.append("Theorem does not pass intent gate.")
            else:
                neg.append(f"<code>kind={kind}</code> not in mechanical-hide policy.")
    else:
        if n_ext > 0:
            neg.append(f"<b>{n_ext}</b> external user(s); privatize would break downstream.")
        if n_sig > 0:
            neg.append(f"<b>{n_sig}</b> signature ref(s); used in the type of same-module decls.")
        # If we already classified as tier-3 hub, keep that
        if kind in {"def", "abbrev"} and n_sig >= 5 and n_ext <= 30:
            verdict = "tier3"
        else:
            verdict = "blocked-noncandidate"

    # Top-30 leverage bonus
    mod = r.get("defining_module", "")
    if mod in top30:
        pos.append(f"Module <code>{h(mod)}</code> is in <b>top-30 leverage</b> (blast cone × edits).")

    return verdict, pos, neg


# ---------------------------------------------------------------------------
# State management — what's already private / in PR / withdrawn
# ---------------------------------------------------------------------------


def update_state(state: dict, census: list[dict], candidate_fqs: set[str],
                 tier_counts: dict[str, int] | None = None,
                 meta_summary: dict[str, int] | None = None) -> dict:
    """Diff the new census against the existing state. Detect transitions:
    - new (decl entered the candidate set this run)
    - merged (was a candidate, now is_private=true in census)
    - dropped (was tracked but no longer a candidate AND not private)

    Records per-run headline numbers (tier counts, meta_consumers stats) so
    the run-history view can show progress over time, not just transitions.

    State is intentionally sparse — we only persist decls that are now or were
    once a candidate, not the whole census (which would be 350K+ rows per run).
    """
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    old_decls = state.setdefault("decls", {})
    by_fq = {r.get("fq_name", ""): r for r in census}

    transitions = {"new": [], "merged": [], "dropped": [], "unchanged": 0}

    # 1. Decls currently in candidate set
    for fq in candidate_fqs:
        r = by_fq.get(fq, {})
        is_priv = bool(r.get("is_private", False))
        old = old_decls.get(fq)
        if old is None:
            entry = {
                "first_seen": today,
                "last_seen": today,
                "status": "merged" if is_priv else "candidate",
            }
            if is_priv:
                entry["merged_at"] = today
                transitions["merged"].append(fq)
            else:
                transitions["new"].append(fq)
            old_decls[fq] = entry
        else:
            old["last_seen"] = today
            if old["status"] == "candidate" and is_priv:
                old["status"] = "merged"
                old["merged_at"] = today
                transitions["merged"].append(fq)
            else:
                transitions["unchanged"] += 1

    # 2. Tracked decls that fell out of the candidate set this run
    for fq, info in list(old_decls.items()):
        if fq in candidate_fqs:
            continue
        if info["status"] in ("merged", "withdrawn", "dropped"):
            continue
        # Not in candidate set anymore — check if it's because it became private
        # (merged) or because policy stopped flagging it (dropped)
        r = by_fq.get(fq, {})
        if r.get("is_private"):
            info["status"] = "merged"
            info["merged_at"] = today
            info["last_seen"] = today
            transitions["merged"].append(fq)
        else:
            info["status"] = "dropped"
            info["dropped_at"] = today
            transitions["dropped"].append(fq)

    # Cumulative merged across all runs to date — the running progress tally.
    # Counts decls whose status is now `merged`, regardless of when.
    n_merged_cumulative = sum(1 for d in old_decls.values() if d.get("status") == "merged")

    runs = state.setdefault("runs", [])
    record = {
        "timestamp": today,
        "n_decls": len(census),
        "n_candidates": len(candidate_fqs),
        "n_new": len(transitions["new"]),
        "n_merged": len(transitions["merged"]),
        "n_dropped": len(transitions["dropped"]),
        "n_merged_cumulative": n_merged_cumulative,
    }
    if tier_counts:
        record["n_tier1"] = tier_counts.get("tier1", 0)
        record["n_tier2"] = tier_counts.get("tier2", 0)
        record["n_tier3"] = tier_counts.get("tier3", 0)
    if meta_summary:
        # Extension-aware census fields (None / 0 if the census predates them).
        record["n_with_meta_consumers"] = meta_summary.get("with_meta_consumers", 0)
        record["n_with_simps_parent"] = meta_summary.get("with_simps_parent", 0)
    runs.append(record)
    return transitions


# ---------------------------------------------------------------------------
# HTML rendering — single file, no external deps
# ---------------------------------------------------------------------------

CSS = """
* { box-sizing: border-box }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  font-size: 13px;
  line-height: 1.45;
  margin: 0;
  padding: 0;
  background: #fafbfc;
  color: #1f2328;
}
header {
  background: #1f2328; color: #fff; padding: 16px 24px;
  display: flex; align-items: baseline; gap: 16px;
}
header h1 { margin: 0; font-size: 18px; font-weight: 600; }
header .meta { color: #8b949e; font-size: 12px; }
nav {
  background: #fff; border-bottom: 1px solid #d0d7de;
  padding: 0 24px; display: flex; gap: 0;
}
nav a {
  padding: 10px 14px; color: #1f2328; text-decoration: none; font-weight: 500;
  border-bottom: 2px solid transparent; cursor: pointer;
}
nav a.active { border-bottom-color: #fd8c73; color: #d1242f; }
.section { padding: 20px 24px; max-width: 1500px; }
.section.hidden { display: none; }
.card-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin: 12px 0 24px; }
.card {
  background: #fff; border: 1px solid #d0d7de; border-radius: 6px; padding: 12px 16px;
}
.card .label { color: #57606a; font-size: 11px; text-transform: uppercase; letter-spacing: 0.05em; }
.card .value { font-size: 22px; font-weight: 600; margin-top: 4px; }
.card .delta { color: #1a7f37; font-size: 11px; margin-top: 4px; }
.card .delta.neg { color: #cf222e; }
table {
  border-collapse: collapse; width: 100%; background: #fff; border: 1px solid #d0d7de;
  font-size: 12px;
}
th, td { padding: 6px 10px; border-bottom: 1px solid #eaeef2; text-align: left; vertical-align: top; }
th {
  background: #f6f8fa; cursor: pointer; user-select: none; font-weight: 600;
  position: sticky; top: 0; z-index: 1;
}
th:hover { background: #e9ecef; }
th.sort-asc::after { content: " ▲"; color: #d1242f; }
th.sort-desc::after { content: " ▼"; color: #d1242f; }
tr:hover { background: #f6f8fa; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
td.module { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 11px; color: #0969da; }
td.fq { font-family: ui-monospace, "SF Mono", Menlo, Consolas, monospace; font-size: 11px; }
.score-bar { display: inline-block; height: 6px; background: #fd8c73; border-radius: 3px; vertical-align: middle; margin-left: 4px; }
.search-box {
  width: 100%; padding: 8px 12px; font-size: 13px; border: 1px solid #d0d7de;
  border-radius: 6px; margin-bottom: 8px;
}
.tag { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 10px; font-weight: 500; }
.tag.tier1 { background: #ddf4ff; color: #0969da; }
.tag.tier2 { background: #fff8c5; color: #9a6700; }
.tag.tier3 { background: #ffd8b5; color: #ba4500; }
.tag.blocked { background: #ffebe9; color: #82071e; }
.tag.merged { background: #dafbe1; color: #1a7f37; }
.tag.candidate { background: #ddf4ff; color: #0969da; }
.tag.private { background: #eaeef2; color: #57606a; }
.num.dim { color: #8c959f; font-style: italic; }
.hint { color: #57606a; font-size: 12px; margin: 4px 0 12px; }
details.legend {
  background: #f6f8fa; border: 1px solid #d1d9e0; border-radius: 6px;
  padding: 10px 14px; margin: 16px 24px;
}
details.legend > summary {
  font-size: 14px; font-weight: 500; color: #1f2328;
  list-style: none; cursor: pointer;
}
details.legend > summary::after {
  content: " ▾"; color: #8c959f;
}
details.legend[open] > summary::after { content: " ▴"; }
.legend-body { padding-top: 8px; }
.legend-body p { margin: 8px 0; color: #1f2328; }
table.legend-table { width: 100%; margin: 12px 0; border-collapse: collapse; }
table.legend-table th, table.legend-table td {
  padding: 8px 10px; vertical-align: top; border-top: 1px solid #d1d9e0;
}
table.legend-table th { text-align: left; background: #fff; color: #57606a; font-weight: 500; }
table.legend-table td:first-child { white-space: nowrap; }
table.legend-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
#section-methodology { padding: 16px 24px 32px; max-width: 1100px; }
#section-methodology h2 { margin-top: 0; }
#section-methodology h3 { margin-top: 28px; padding-bottom: 4px; border-bottom: 1px solid #d1d9e0; }
#section-methodology p, #section-methodology li { color: #1f2328; }
#section-methodology table.legend-table { background: #f6f8fa; border-radius: 6px; }
#section-methodology pre.formula {
  background: #f6f8fa; border: 1px solid #d1d9e0; border-radius: 6px;
  padding: 12px 16px; font-size: 12px; line-height: 1.5;
  overflow-x: auto; margin: 12px 0;
}
#section-methodology ul { padding-left: 22px; }
#section-methodology ul li { margin: 4px 0; }
.tag.top30 { background: #ffd8b5; color: #82071e; font-weight: 600; }
details { margin: 4px 0; }
details summary { cursor: pointer; padding: 2px 0; font-weight: 500; }
details summary:hover { color: #0969da; }
.signals { margin-top: 4px; padding-left: 18px; }
.signals li { margin: 2px 0; font-size: 11px; }
.signals .yes { color: #1a7f37; }
.signals .no { color: #cf222e; }
.muted { color: #57606a; font-size: 11px; }
code { background: #f6f8fa; padding: 1px 4px; border-radius: 3px; font-size: 11px; }
.right { float: right; }
"""


def render_legend(stats: dict) -> str:
    """Top-of-dashboard navigation guide. Explains how candidate decls are
    grouped (tier 1 / 2 / 3) and what each tab shows."""
    t1 = stats["tier1_n"]
    t2 = stats["tier2_n"]
    t3 = stats["tier3_n"]
    return f"""
<details class="legend" open>
<summary><b>How to read this dashboard</b>: what the tiers mean and where to look</summary>
<div class="legend-body">
<p>Candidates are split into three <b>tiers</b> by reference shape. The
tabs match the tiers.</p>
<table class="legend-table">
  <thead>
    <tr><th>Tier</th><th>What it groups</th><th>Count</th><th>Where it shows</th></tr>
  </thead>
  <tbody>
    <tr>
      <td><span class="tag tier1">Tier&nbsp;1</span></td>
      <td><b>One row = one decl.</b> 0 external users, 0 intra-module refs,
          policy-clean. Applied as a single <code>private</code> edit.</td>
      <td class="num"><b>{t1:,}</b></td>
      <td>Rolled up into Tier-2 bundles. Each bundle's <code>decls</code>
          column lists its tier-1 members.</td>
    </tr>
    <tr>
      <td><span class="tag tier2">Tier&nbsp;2</span></td>
      <td><b>One row = one module.</b> Modules with ≥ 3 tier-1 decls.
          One PR per module privatizes its tier-1 set in one commit.
          Score: blast-cone CP × T30 multiplier (3× if top-30 by leverage)
          × log(1+edits).</td>
      <td class="num"><b>{t2:,}</b></td>
      <td>Top-25 on Summary; full list under <i>Tier&nbsp;2 — Module bundles</i>.</td>
    </tr>
    <tr>
      <td><span class="tag tier3">Tier&nbsp;3</span></td>
      <td><b>One row = one decl.</b> A def whose type is referenced by ≥ 5
          decls in the same module, with ≤ 30 external users.
          Action: move the hub and its dependents into a sub-module that
          the parent imports privately.</td>
      <td class="num"><b>{t3:,}</b></td>
      <td><i>Tier&nbsp;3 — Encapsulation candidates</i> tab.</td>
    </tr>
  </tbody>
</table>
<p><span class="tag top30">T30</span>: the 30 mathlib modules with the
highest leverage (edits × cascade-cost) over the last 1,500 master
commits. Acts as a 3× multiplier on the Tier-2 score. Full formula and
selection rules under <i>Methodology</i>.</p>

<p><b>Other tabs.</b>
<i>Methodology</i>: how candidates are selected, bundled, and scored.
<i>Why some decls are excluded</i>: per-decl reasoning for non-candidates
(blocked attribute, forbidden name pattern, registered in an extension's
by-name registry, etc.).
<i>Run history</i>: per-run tier counts and transitions (new / merged /
dropped).</p>
</div>
</details>
"""


def render_methodology() -> str:
    """Full-tab methodology writeup: how candidates are selected, bundled,
    scored, and excluded. Mirrors LANDSCAPE.md but framed for a dashboard
    reader (less prose, more tables and definitions)."""
    return """
<h2>Methodology</h2>
<p>The dashboard lists mathlib4 declarations whose reference shape and
attribute profile permit a <code>private</code> annotation. A
<code>private</code> decl's body lives in <code>.olean.private</code>
and is excluded from the public <code>.olean</code>. Body-only edits to
<code>private</code> decls leave downstream <code>.olean.hash</code>
unchanged. Cache-cut empirics: <code>REPORT.md</code>. Theoretical
aggregate ceiling: ~92% rebuild-CP savings once api-hash caching ships.</p>

<h3>1. Selecting candidate declarations</h3>

<p><code>scripts/decl_census/DeclCensus.lean</code> walks every
declaration in mathlib's elaborator state. Per decl, it emits a JSONL
row with fq_name, defining module, kind, attributes, name pattern,
has-docstring, and reference counts from <code>Expr.foldConsts</code>
over <code>info.type</code> and <code>info.value?</code>.</p>

<table class="legend-table">
  <thead><tr><th>Field</th><th>What it counts</th></tr></thead>
  <tbody>
    <tr><td><code>n_external_users</code></td>
        <td>References from other modules.</td></tr>
    <tr><td><code>n_intra_module_refs</code></td>
        <td>References from the same module.</td></tr>
    <tr><td><code>n_signature_refs</code></td>
        <td>Same-module references that occur in the type signature, not the body.</td></tr>
    <tr><td><code>name_pattern</code></td>
        <td>Classifier flag: <code>normal</code>, <code>underscore_prefix</code>, <code>simps_projection</code>, <code>auto_derived</code>, etc.</td></tr>
    <tr><td><code>meta_consumers</code></td>
        <td>Extension registries (<code>@[simps]</code>, <code>@[simp]</code>, …) that contain this decl by name.</td></tr>
  </tbody>
</table>

<h3>2. Filtering</h3>

<p>Each decl passes through <code>policy.toml</code>'s <code>hard_blocks</code>
before becoming a candidate. <code>policy.toml</code> is consumed by
rerank, apply, and the dashboard.</p>

<table class="legend-table">
  <thead><tr><th>Layer</th><th>Blocks</th><th>Reason</th></tr></thead>
  <tbody>
    <tr><td><code>forbidden_attrs</code></td>
        <td><code>@[reducible]</code>, <code>@[implicit_reducible]</code>,
            <code>@[deprecated]</code>, <code>@[inline]</code></td>
        <td>Semantic attributes whose behavior interacts with visibility.</td></tr>
    <tr><td><code>build_rejected_attrs</code></td>
        <td><code>@[simp]</code>, <code>@[norm_cast]</code>, <code>@[ext]</code>,
            <code>@[macro]</code>, <code>@[fun_prop]</code>, <code>@[positivity]</code>,
            <code>@[norm_num]</code>, <code>@[simps]</code>, <code>@[instance]</code>, …</td>
        <td>Extensions that look up the decl by name at attribute
            elaboration. Lean rejects <code>private</code> on a decl carrying
            any of these.</td></tr>
    <tr><td><code>forbidden_name_patterns</code></td>
        <td><code>simps_projection</code> (decls under <code>Foo.Simps.*</code>).</td>
        <td>Generated by <code>@[simps]</code> on the parent struct.
            Consumed by name without carrying an attribute themselves.</td></tr>
    <tr><td><code>forbidden_module_prefixes</code></td>
        <td><code>Mathlib.Tactic.</code>, <code>Mathlib.Meta.</code>, <code>Mathlib.Lean.</code></td>
        <td>Elaborator-helper directories. Candidates from here are
            rejected at apply (forbidden-attr filter) or reverted at build.
            Pre-filtering drops ~14% of candidate churn.</td></tr>
  </tbody>
</table>

<p>Soft block: theorems and lemmas with a docstring and
<code>name_pattern=normal</code> are treated as public API regardless of
external-user count.</p>

<h3>3. Tiering</h3>

<table class="legend-table">
  <thead><tr><th>Tier</th><th>Membership</th><th>Unit of action</th></tr></thead>
  <tbody>
    <tr>
      <td><span class="tag tier1">Tier&nbsp;1</span></td>
      <td><code>n_external_users == 0</code>, <code>n_signature_refs == 0</code>,
          intent-safe, policy-clean. Body refs in the same module are
          allowed: private decls remain visible inside the defining module
          so proofs continue to type-check.</td>
      <td>One <code>private</code> edit per decl.</td>
    </tr>
    <tr>
      <td><span class="tag tier2">Tier&nbsp;2</span></td>
      <td>Modules with ≥ 3 Tier-1 decls (grouped by <code>defining_module</code>).</td>
      <td>One PR per module.</td>
    </tr>
    <tr>
      <td><span class="tag tier3">Tier&nbsp;3</span></td>
      <td><code>kind ∈ {def, abbrev}</code>, <code>n_signature_refs ≥ 5</code>, <code>n_external_users ≤ 30</code>.</td>
      <td>Move the hub and its in-signature dependents into a
          sub-namespace that the parent imports privately. Worked example:
          <a href="https://github.com/leanprover-community/mathlib4/pull/38702">mathlib4 #38702</a>.</td>
    </tr>
  </tbody>
</table>

<h3>4. Scoring</h3>

<p>Per-module weight, used to rank tier-2 bundles:</p>

<pre class="formula">
score(m) = (1 − exp(−bcp / 100))    × (3 if T30 else 1)    × (1 + log(1+edits) / 3)
           ─────────────────────      ─────────────────      ──────────────────────
           cascade-cost saturation    leverage multiplier    edit-frequency factor
</pre>

<table class="legend-table">
  <thead><tr><th>Term</th><th>Definition</th><th>Source</th></tr></thead>
  <tbody>
    <tr><td><code>bcp</code></td>
        <td>Blast-cone critical-path seconds: the CP of the induced
            subgraph over all transitive importers of <i>m</i>. Per-module
            property of the build graph; independent of commit content.</td>
        <td><code>pipeline/p07_churn_blast.py</code></td></tr>
    <tr><td><code>T30</code></td>
        <td>1 if <i>m</i> is in the 30 highest-leverage modules in the
            1,500-commit window, else 0. Leverage = edits × bcp.</td>
        <td><code>pipeline/out/churn_blast.json:top_leverage</code></td></tr>
    <tr><td><code>edits</code></td>
        <td>Commits in the 1,500-commit window that touched
            <i>m</i>'s source.</td>
        <td><code>git log</code> walk over <code>master</code>.</td></tr>
  </tbody>
</table>

<p>Per-tier scoring:</p>
<ul>
  <li><b>Tier 1</b>: each decl inherits its module's <code>score(m)</code>.</li>
  <li><b>Tier 2</b>: bundle score is <code>score(m)</code> weighted by
      <code>n_decls</code>.</li>
  <li><b>Tier 3</b>: <code>bcp × n_signature_refs</code>.</li>
</ul>

<h3>5. Top-30 leverage list (T30)</h3>

<p>Computed once per pipeline run from a walk of 1,500 commits of mathlib
master, attributing each commit's blast-cone CP to the modules it
touched, sorted by aggregate leverage. Current top-5:</p>

<table class="legend-table">
  <thead><tr><th>#</th><th>Module</th><th>Edits (1500-commit window)</th><th>blast-CP-s per edit</th><th>Leverage</th></tr></thead>
  <tbody>
    <tr><td>1</td><td><code>Mathlib.SetTheory.Cardinal.Cofinality</code></td><td class="num">25</td><td class="num">376.8</td><td class="num">9,420</td></tr>
    <tr><td>2</td><td><code>Mathlib.SetTheory.Ordinal.Basic</code></td><td class="num">20</td><td class="num">399.7</td><td class="num">7,994</td></tr>
    <tr><td>3</td><td><code>Mathlib.Tactic.Translate.Core</code></td><td class="num">10</td><td class="num">713.8</td><td class="num">7,138</td></tr>
    <tr><td>4</td><td><code>Mathlib.Data.List.Basic</code></td><td class="num">9</td><td class="num">669.7</td><td class="num">6,027</td></tr>
    <tr><td>5</td><td><code>Mathlib.Tactic.Translate.ToDual</code></td><td class="num">8</td><td class="num">707.8</td><td class="num">5,663</td></tr>
  </tbody>
</table>

<p>Membership shifts as the import graph churns. The dashboard re-reads
the list on every regen.</p>

<h3>6. Verification</h3>

<p>Each retained privatization is verified by <code>lake build</code>.
Two pipelines:</p>
<ul>
  <li><b>Bulk</b> (<code>pr1/bulk_apply.py</code> + <code>bulk_iterate.sh</code>):
      apply every tier-1 candidate in one commit, then loop build →
      revert breaking decls → rebuild until convergence. Output: one
      diff, full-mathlib verified.</li>
  <li><b>Per-bundle</b> (<code>pr1/iterate_bundle.sh</code>): apply per
      module with a 4-importer build cap. Output: a series of small
      commits.</li>
</ul>
<p>Both pipelines end with a full-mathlib build. Apply/revert unit
tests: <code>tests/</code>. Refer to <code>LANDSCAPE.md §6.5</code>.</p>
"""


def render_summary_cards(stats: dict) -> str:
    cards = []
    for label, value, delta in stats:
        delta_html = ""
        if delta is not None:
            cls = "delta" + (" neg" if delta < 0 else "")
            sign = "+" if delta >= 0 else ""
            delta_html = f'<div class="{cls}">{sign}{delta} since last run</div>'
        cards.append(
            f'<div class="card"><div class="label">{h(label)}</div>'
            f'<div class="value">{h(str(value))}</div>{delta_html}</div>'
        )
    return f'<div class="card-grid">{"".join(cards)}</div>'


def render_explanation_signals(pos: list[str], neg: list[str]) -> str:
    items = []
    for p in pos:
        items.append(f'<li class="yes">✓ {p}</li>')
    for n in neg:
        items.append(f'<li class="no">✗ {n}</li>')
    return f'<ul class="signals">{"".join(items)}</ul>' if items else ""


def render_tier2_table(tier2: list[dict], top30: set[str], state_decls: dict,
                       table_id: str = "tier2-table") -> str:
    rows_html = []
    for b in tier2:
        m = b["module"]
        n_decls = b.get("n_decls", 0)
        score = b.get("score", 0)
        is_t30 = m in top30
        edits = b.get("module_edits") or 0
        decls_in_bundle = b.get("decls", [])
        # Count merged across the FULL bundle, not just the preview
        n_merged = sum(1 for d in decls_in_bundle if state_decls.get(d, {}).get("status") == "merged")
        decls_html_items = []
        for fq in decls_in_bundle[:25]:
            sd = state_decls.get(fq, {})
            status = sd.get("status", "candidate")
            decls_html_items.append(
                f'<li>{h(fq)} <span class="tag {status}">{status}</span></li>'
            )
        if len(decls_in_bundle) > 25:
            decls_html_items.append(f'<li class="muted">… and {len(decls_in_bundle)-25} more</li>')
        decls_html = f'<ul class="signals">{"".join(decls_html_items)}</ul>'

        if n_merged >= len(decls_in_bundle) and n_merged > 0:
            action = '<span class="tag merged">all merged</span>'
        elif n_merged > 0:
            action = f'<span class="tag candidate">{n_merged}/{len(decls_in_bundle)} merged</span>'
        else:
            action = '<span class="tag candidate">ready to PR</span>'

        rows_html.append(f"""
<tr data-search="{h(m.lower())}" data-score="{score:.2f}" data-decls="{n_decls}">
  <td class="num">{score:.1f}</td>
  <td class="num">{n_decls}</td>
  <td>{'<span class="tag top30">T30</span>' if is_t30 else ''}</td>
  <td class="num">{edits or '—'}</td>
  <td class="module">
    <details>
      <summary>{h(m)}</summary>
      {decls_html}
    </details>
  </td>
  <td>{action}</td>
</tr>""")
    return f"""
<input type="text" class="search-box" placeholder="Filter modules…" oninput="filterRows(this, '{table_id}')"/>
<table id="{table_id}">
  <thead>
    <tr>
      <th data-type="num" onclick="sortTable('{table_id}', 0, 'num')">Score</th>
      <th data-type="num" onclick="sortTable('{table_id}', 1, 'num')">N decls</th>
      <th>Top-30</th>
      <th data-type="num" onclick="sortTable('{table_id}', 3, 'num')">Edits</th>
      <th onclick="sortTable('{table_id}', 4, 'str')">Module / Decls</th>
      <th>Action</th>
    </tr>
  </thead>
  <tbody>
    {"".join(rows_html)}
  </tbody>
</table>
"""


def _split_co_located(decls: list[str]) -> tuple[list[str], list[str]]:
    """Split a `signature_referenced_by_intra` list into (user-facing, auto-derived).

    Auto-derived names: proof obligations (`._proof_N`), equation lemmas
    (`._eq_N`), simp markers (`._simp_N`), and the `_private.MOD.0.NAME`
    wrapper Lean uses for already-private decls. These crowd the visible
    list without adding meaning, so they are kept under a separate fold.
    """
    AUTO_TOKENS = ("._proof_", "._eq_", "._simp_", "._unsafe_rec_",
                   "._mutual_", ".match_", "._cstage")
    user, auto = [], []
    for fq in decls:
        if fq.startswith("_private.") or any(t in fq for t in AUTO_TOKENS):
            auto.append(fq)
        else:
            user.append(fq)
    return user, auto


def render_tier3_intro() -> str:
    """Top-of-page explanation for the Tier-3 view: what a hub is, how we
    select them, and what each suggested action means. Keep this concise but
    self-contained so a reader landing here doesn't need to bounce to the
    Methodology tab."""
    return """
<details class="legend" open>
<summary><b>Tier-3 selection</b>: heuristic and suggested actions</summary>
<div class="legend-body">

<p>Each row is one declaration. Acting on the row means moving the
declaration plus the same-module declarations that mention it in their
type signature into a sub-namespace that the parent imports privately.</p>

<h3>Hub definition</h3>

<p>A declaration <code>D</code> in module <code>M</code> is a hub when at
least 5 of <code>M</code>'s other declarations mention <code>D</code> in
their type signature, not just their proof body. Type-signature
references cannot be removed by editing only the consumer; body
references can.</p>

<h3>Selection</h3>

<table class="legend-table">
  <thead><tr><th>Filter</th><th>Threshold</th><th>Reason</th></tr></thead>
  <tbody>
    <tr><td><code>kind</code></td>
        <td><code>def</code> or <code>abbrev</code></td>
        <td>Theorem/lemma decls are facts; the encapsulation pattern
            applies to constructive definitions.</td></tr>
    <tr><td><code>n_signature_refs</code></td>
        <td><b>≥ 5</b></td>
        <td>Smaller clusters do not warrant a sub-module split.</td></tr>
    <tr><td><code>n_external_users</code></td>
        <td><b>≤ 30</b></td>
        <td>Each external consumer must add a <code>public import</code>
            of the new sub-module.</td></tr>
    <tr><td><code>policy.toml</code> hard blocks</td>
        <td></td>
        <td>Same gates as Tier 1 and Tier 2 (forbidden attributes,
            name patterns, module prefixes).</td></tr>
  </tbody>
</table>

<h3>Suggested actions</h3>

<p>Selected by <code>n_external_users</code>:</p>

<table class="legend-table">
  <thead><tr><th><code>n_external_users</code></th><th>Action</th><th>Mechanics</th></tr></thead>
  <tbody>
    <tr><td class="num"><b>0</b></td>
        <td><b>Privatize wholesale (cluster + hub)</b></td>
        <td>Mark the hub and every in-signature dependent
            <code>private</code>. One file edited, no sub-module split.</td></tr>
    <tr><td class="num"><b>1 – 10</b></td>
        <td><b>Sub-module encapsulation refactor</b></td>
        <td>Split <code>Mathlib/Foo.lean</code> into
            <code>Mathlib/Foo.lean</code> + <code>Mathlib/Foo/Internal.lean</code>.
            The parent <code>private import</code>s the new sub-module.
            Each external consumer adds a <code>public import</code>.
            Worked example: <a href="https://github.com/leanprover-community/mathlib4/pull/38702">mathlib4 #38702</a>.</td></tr>
    <tr><td class="num"><b>11 – 30</b></td>
        <td><b>Discuss first</b></td>
        <td>Consumer-side work scales linearly with external users.
            The refactor cost may exceed the cache-cut benefit, or the
            hub may be public API.</td></tr>
  </tbody>
</table>

<p>Each row below is one hub. The <i>Co-located decls</i> cell expands
to the same-module declarations that would move with it. Auto-derived
names (proof obligations, equation lemmas, simp markers) are folded
under a nested toggle.</p>
</div>
</details>
"""


def render_tier3_table(tier3: list[dict], top30: set[str], state_decls: dict) -> str:
    rows_html = []
    for r in tier3:
        fq = r["fq_name"]
        m = r["defining_module"]
        score = r.get("score", 0)
        n_sig = r.get("n_signature_refs", 0)
        n_ext = r.get("n_external_users", 0)
        has_doc = r.get("has_docstring", False)
        is_t30 = m in top30
        sd = state_decls.get(fq, {})
        status = sd.get("status", "candidate")

        if n_ext == 0:
            action = "Privatize wholesale (cluster + hub)"
        elif n_ext <= 10:
            action = (f"Sub-module encapsulation refactor; {n_ext} consumer(s) "
                      f"add <code>public import</code>")
        else:
            action = f"Discuss first ({n_ext} consumers; heavier consumer-side work)"

        # Sibling decls grouped under this hub. Cap at 25 user-facing names
        # before truncating; auto-derived names (proof obls, equation lemmas)
        # go under a nested fold.
        co_located = r.get("signature_referenced_by_intra", []) or []
        user, auto = _split_co_located(co_located)
        items: list[str] = []
        for d in user[:25]:
            items.append(f"<li><code>{h(d)}</code></li>")
        if len(user) > 25:
            items.append(f'<li class="muted">… and {len(user)-25} more user-facing</li>')
        if auto:
            auto_items = "".join(
                f"<li><code>{h(a)}</code></li>" for a in auto[:25]
            )
            if len(auto) > 25:
                auto_items += f'<li class="muted">… and {len(auto)-25} more</li>'
            items.append(
                f'<li><details><summary class="muted">'
                f'+ {len(auto)} auto-derived (<code>._proof_*</code>, '
                f'<code>._eq_*</code>, <code>._simp_*</code>, '
                f'<code>_private.*</code>)</summary>'
                f'<ul class="signals">{auto_items}</ul></details></li>'
            )
        if not items:
            co_located_html = '<span class="muted">(none recorded)</span>'
        else:
            co_located_html = (
                f'<details><summary>{len(user)} user-facing'
                + (f' + {len(auto)} auto-derived' if auto else '')
                + ' co-located decl(s) reference '
                + f'<code>{h(r["leaf"])}</code> in their type</summary>'
                + f'<ul class="signals">{"".join(items)}</ul></details>'
            )

        rows_html.append(f"""
<tr data-search="{h((fq + ' ' + m + ' ' + ' '.join(user[:10])).lower())}" data-score="{score:.2f}">
  <td class="num">{score:.1f}</td>
  <td class="num">{n_sig}</td>
  <td class="num">{n_ext}</td>
  <td>{'Y' if has_doc else '·'}</td>
  <td class="fq">{h(fq)}</td>
  <td class="module">{h(m)}{' <span class="tag top30">T30</span>' if is_t30 else ''}</td>
  <td>{co_located_html}</td>
  <td><span class="tag {status}">{status}</span></td>
  <td>{action}</td>
</tr>""")
    return f"""
<p class='hint'>Each row is one hub declaration. The
<i>Co-located decls</i> column lists same-module decls that reference
the hub in their type signature. These would move into a sub-module
alongside the hub if extracted. Auto-derived names (proof obligations,
equation lemmas) are folded under a nested toggle.</p>
<input type="text" class="search-box" placeholder="Filter hubs / modules / co-located decls…" oninput="filterRows(this, 'tier3-table')"/>
<table id="tier3-table">
  <thead>
    <tr>
      <th data-type="num" onclick="sortTable('tier3-table', 0, 'num')">Score</th>
      <th data-type="num" onclick="sortTable('tier3-table', 1, 'num')">Sig refs</th>
      <th data-type="num" onclick="sortTable('tier3-table', 2, 'num')">Ext users</th>
      <th>Doc</th>
      <th onclick="sortTable('tier3-table', 4, 'str')">Hub</th>
      <th onclick="sortTable('tier3-table', 5, 'str')">Module</th>
      <th>Co-located decls</th>
      <th>Status</th>
      <th>Suggested action</th>
    </tr>
  </thead>
  <tbody>
    {"".join(rows_html)}
  </tbody>
</table>
"""


def render_excluded_examples(census: list[dict], top30: set[str], n: int = 50) -> str:
    """Sample of decls that DIDN'T make any tier, with reasons. Helps understand the filter."""
    by_reason = defaultdict(list)
    for r in census:
        if r.get("is_private"):
            continue  # already private; show separately
        verdict, pos, neg = explain_decl(r, top30)
        if verdict.startswith("blocked-"):
            by_reason[verdict].append((r, pos, neg))

    rows_html = []
    for reason, items in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        rows_html.append(f"<h3>{h(reason)} <span class='muted'>({len(items):,} decls)</span></h3>")
        sample_html = []
        for r, pos, neg in items[:8]:
            sample_html.append(
                f"<tr>"
                f"<td class='fq'>{h(r['fq_name'])}</td>"
                f"<td class='module'>{h(r['defining_module'])}</td>"
                f"<td>{h(r.get('kind','?'))}</td>"
                f"<td>{render_explanation_signals(pos, neg)}</td>"
                f"</tr>"
            )
        rows_html.append(
            f"<table style='margin-bottom:16px'>"
            f"<thead><tr><th>Decl</th><th>Module</th><th>Kind</th><th>Signals</th></tr></thead>"
            f"<tbody>{''.join(sample_html)}</tbody></table>"
        )
    return "".join(rows_html)


def render_per_run_history(state: dict) -> str:
    """Per-run table showing both the snapshot (tier counts, total candidates)
    and the deltas (new / merged / dropped this run). The cumulative-merged
    column tracks the full privatization progress over time."""
    runs = state.get("runs", [])
    if not runs:
        return "<p>No previous runs.</p>"
    rows = []
    for r in runs[-20:][::-1]:
        # Optional fields absent on older runs render as a dim em-dash.
        def fmt(key: str) -> str:
            v = r.get(key)
            if v is None:
                return "<td class='num dim'>—</td>"
            return f"<td class='num'>{v:,}</td>"
        rows.append(
            f"<tr><td>{h(r['timestamp'])}</td>"
            f"<td class='num'>{r['n_decls']:,}</td>"
            f"<td class='num'>{r['n_candidates']:,}</td>"
            + fmt("n_tier1") + fmt("n_tier2") + fmt("n_tier3")
            + f"<td class='num'>{r['n_new']:,}</td>"
            f"<td class='num'>{r['n_merged']:,}</td>"
            f"<td class='num'>{r['n_dropped']:,}</td>"
            + fmt("n_merged_cumulative")
            + fmt("n_with_meta_consumers")
            + "</tr>"
        )
    return f"""
<p class='hint'>Snapshot columns (Total / Candidates / Tier-1-3 / Meta-consumers) show the queue state. Delta columns (New / Merged / Dropped) show what changed between runs. <code>cum. merged</code> is the cumulative total of decls successfully privatized across all runs.</p>
<table>
  <thead><tr>
    <th>Run</th>
    <th>Total decls</th><th>Candidates</th>
    <th>Tier 1</th><th>Tier 2</th><th>Tier 3</th>
    <th>New</th><th>Merged</th><th>Dropped</th>
    <th>cum. merged</th>
    <th>w/ <code>@[simps]</code></th>
  </tr></thead>
  <tbody>{"".join(rows)}</tbody>
</table>
"""


JS = """
function sortTable(tableId, colIdx, type) {
  const t = document.getElementById(tableId);
  const tbody = t.tBodies[0];
  const rows = Array.from(tbody.rows);
  const ths = t.tHead.rows[0].cells;
  const isAsc = ths[colIdx].classList.contains('sort-asc');
  for (const th of ths) th.classList.remove('sort-asc', 'sort-desc');
  ths[colIdx].classList.add(isAsc ? 'sort-desc' : 'sort-asc');
  rows.sort((a, b) => {
    let av = a.cells[colIdx].textContent.trim();
    let bv = b.cells[colIdx].textContent.trim();
    if (type === 'num') {
      av = parseFloat(av.replace(/[^\\d.\\-]/g, '')) || 0;
      bv = parseFloat(bv.replace(/[^\\d.\\-]/g, '')) || 0;
      return isAsc ? av - bv : bv - av;
    }
    return isAsc ? av.localeCompare(bv) : bv.localeCompare(av);
  });
  for (const r of rows) tbody.appendChild(r);
}

function filterRows(input, tableId) {
  const q = input.value.toLowerCase();
  const tbody = document.getElementById(tableId).tBodies[0];
  for (const row of tbody.rows) {
    const haystack = (row.dataset.search || row.textContent).toLowerCase();
    row.style.display = haystack.includes(q) ? '' : 'none';
  }
}

function showSection(name) {
  document.querySelectorAll('.section').forEach(s => s.classList.add('hidden'));
  document.getElementById('section-' + name).classList.remove('hidden');
  document.querySelectorAll('nav a').forEach(a => a.classList.remove('active'));
  document.querySelector('nav a[data-section="' + name + '"]').classList.add('active');
}
"""


def build_html(stats: dict, tier2: list[dict], tier3: list[dict],
               census: list[dict], top30: set[str], state: dict,
               transitions: dict) -> str:
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Compute deltas for headline cards
    runs = state.get("runs", [])
    prev_run = runs[-2] if len(runs) >= 2 else None

    # Tier deltas vs previous run (if recorded)
    def tier_delta(key: str) -> int | None:
        if not prev_run or key not in prev_run:
            return None
        return stats[f"{key.replace('n_tier', 'tier')}_n"] - prev_run[key]

    cards = [
        ("Mathlib decls scanned", f"{len(census):,}",
         (len(census) - prev_run["n_decls"]) if prev_run else None),
        ("Tier-1 candidates", f"{stats['tier1_n']:,}", tier_delta("n_tier1")),
        ("Tier-2 bundles", f"{stats['tier2_n']:,}", tier_delta("n_tier2")),
        ("Tier-3 encap hubs", f"{stats['tier3_n']:,}", tier_delta("n_tier3")),
        ("New since last run", f"{len(transitions['new']):,}", None),
        ("Merged (now private)", f"{len(transitions['merged']):,}", None),
    ]
    # Extension-aware census fields. Only show the cards if the census
    # actually populated them — older censuses leave them at zero, in which
    # case displaying "0" gives the misleading impression of "we checked
    # and found none" rather than "the census didn't carry that info".
    if stats.get("meta_consumers_n", 0) or stats.get("simps_parent_n", 0):
        cards.append(("Decls in extension registry",
                      f"{stats['meta_consumers_n']:,}", None))
        cards.append(("@[simps]-derived projections",
                      f"{stats['simps_parent_n']:,}", None))

    state_decls = state.get("decls", {})

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Mathlib Privatization Dashboard</title>
<style>{CSS}</style>
</head>
<body>
<header>
  <h1>Mathlib Privatization Candidate Dashboard</h1>
  <span class="meta">Last updated: {h(timestamp)}</span>
</header>
<nav>
  <a class="active" data-section="summary" onclick="showSection('summary')">Summary</a>
  <a data-section="methodology" onclick="showSection('methodology')">Methodology</a>
  <a data-section="tier2" onclick="showSection('tier2')">Tier 2 — Module bundles</a>
  <a data-section="tier3" onclick="showSection('tier3')">Tier 3 — Encapsulation candidates</a>
  <a data-section="excluded" onclick="showSection('excluded')">Why some decls are excluded</a>
  <a data-section="history" onclick="showSection('history')">Run history</a>
</nav>

<div class="section" id="section-summary">
{render_legend(stats)}
{render_summary_cards(cards)}
<h2>Top 25 module bundles by impact</h2>
<p class="muted">Modules with mechanically-safe privatization available.
Each row groups all tier-1 candidates in that module. Score combines blast-cone CP × top-30 multiplier × log(1+edits).</p>
{render_tier2_table(tier2[:25], top30, state_decls, table_id="tier2-summary-table")}
</div>

<div class="section hidden" id="section-methodology">
{render_methodology()}
</div>

<div class="section hidden" id="section-tier2">
<h2>All tier-2 module bundles ({len(tier2)})</h2>
<p class="muted">Sortable and searchable. Click a row's module to see candidate decls and current status.</p>
{render_tier2_table(tier2, top30, state_decls, table_id="tier2-table")}
</div>

<div class="section hidden" id="section-tier3">
<h2>Tier-3 sub-module encapsulation candidates ({len(tier3)})</h2>
{render_tier3_intro()}
<p class='hint'>Showing top 1,000 of {len(tier3):,} by score. The full
list is in <code>data/ranked_candidates.jsonl.gz</code>.</p>
{render_tier3_table(tier3[:1000], top30, state_decls)}
</div>

<div class="section hidden" id="section-excluded">
<h2>Why some decls are excluded from the candidate queue</h2>
<p class="muted">Decls rejected by the framework, grouped by reason. Use to sanity-check the policy.</p>
{render_excluded_examples(census, top30)}
</div>

<div class="section hidden" id="section-history">
<h2>Run history</h2>
<p class="muted">Snapshot stats per run. Track the privatization queue progress over time.</p>
{render_per_run_history(state)}
</div>

<script>{JS}</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--census", default=str(CENSUS))
    ap.add_argument("--ranked", default=str(RANKED))
    ap.add_argument("--churn", default=str(CHURN))
    ap.add_argument("--state", default=str(STATE))
    ap.add_argument("--out", default=str(OUT_HTML))
    args = ap.parse_args()

    print(f"loading {args.census}…", file=sys.stderr)
    census = load_jsonl(Path(args.census))
    print(f"  {len(census):,} decls", file=sys.stderr)

    print(f"loading {args.ranked}…", file=sys.stderr)
    ranked = load_jsonl(Path(args.ranked))
    tier1 = [r for r in ranked if r.get("tier") == "1_solo"]
    tier2 = [r for r in ranked if r.get("tier") == "2_bundle"]
    tier3 = [r for r in ranked if r.get("tier") == "3_encap"]
    print(f"  tier1={len(tier1):,}, tier2={len(tier2):,}, tier3={len(tier3):,}",
          file=sys.stderr)

    print(f"loading {args.churn}…", file=sys.stderr)
    churn = json.loads(Path(args.churn).read_text())
    top30 = {r["module"] for r in churn.get("top_leverage", [])}
    print(f"  top-30 modules loaded", file=sys.stderr)

    # The "candidate set" tracked by state = anything in tier 1, 2 (rolled up to
    # decls), or 3. Tier-2 rows are bundles, so unroll their `decls` list.
    candidate_fqs: set[str] = set()
    for r in tier1:
        candidate_fqs.add(r["fq_name"])
    for r in tier3:
        candidate_fqs.add(r["fq_name"])
    for b in tier2:
        for fq in b.get("decls", []):
            candidate_fqs.add(fq)
    print(f"  candidate set: {len(candidate_fqs):,} unique decls", file=sys.stderr)

    # Summary of the extension-aware census fields (will be 0/0 when the
    # census predates them; populated once the meta branch is rerun).
    meta_summary = {
        "with_meta_consumers": sum(1 for r in census if r.get("meta_consumers")),
        "with_simps_parent": sum(1 for r in census if r.get("simps_parent")),
    }
    if meta_summary["with_meta_consumers"] or meta_summary["with_simps_parent"]:
        print(f"  meta_consumers populated: {meta_summary['with_meta_consumers']:,}, "
              f"simps_parent populated: {meta_summary['with_simps_parent']:,}",
              file=sys.stderr)

    state = load_state(Path(args.state))
    transitions = update_state(
        state, census, candidate_fqs,
        tier_counts={"tier1": len(tier1), "tier2": len(tier2), "tier3": len(tier3)},
        meta_summary=meta_summary,
    )
    print(f"  transitions: new={len(transitions['new'])}, "
          f"merged={len(transitions['merged'])}, dropped={len(transitions['dropped'])}",
          file=sys.stderr)

    stats = {
        "tier1_n": len(tier1),
        "tier2_n": len(tier2),
        "tier3_n": len(tier3),
        "meta_consumers_n": meta_summary["with_meta_consumers"],
        "simps_parent_n": meta_summary["with_simps_parent"],
    }

    print("rendering HTML…", file=sys.stderr)
    html = build_html(stats, tier2, tier3, census, top30, state, transitions)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html)
    print(f"  wrote {out} ({out.stat().st_size:,} bytes)", file=sys.stderr)

    save_state(Path(args.state), state)
    print(f"  saved state {args.state}", file=sys.stderr)


if __name__ == "__main__":
    main()
