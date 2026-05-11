# mathlib-hide-decls

A pipeline for finding mathlib4 declarations that can be marked `private`,
verified by `lake build`, and ranked by the rebuild-CP impact of the
modules they live in.

**Live dashboard**: <https://marcelolynch.github.io/mathlib-hide-decls/>

## What this repository contains

| directory | role |
|---|---|
| `census/` | A standalone Lean 4 project. Walks every declaration in mathlib's elaborator state and emits one JSONL row per decl. |
| `pipeline/` | Python pipeline: re-ranks the census output into three tiers, applies `private` annotations, drives the iterate-revert loop, generates the dashboard. |
| `data/` | Latest census + ranking + churn-cone graph + per-snapshot archives. Compressed JSONL. |
| `site/` | Generated HTML dashboard. Served by GitHub Pages. |
| `docs/` | Design, methodology, and results documentation. |

## How privatization helps incremental builds

Lean 4.10's module system separates each compiled module into three
artifacts:

| artifact | contents | hash file |
|---|---|---|
| `M.olean` | public declarations as seen by importers | `M.olean.hash` |
| `M.olean.private` | bodies of `private` declarations | `M.olean.private.hash` |
| `M.olean.server` | server-only metadata (positions, docstrings) | `M.olean.server.hash` |

A downstream module's incremental rebuild keys on `M.olean.hash`. The
hash includes the bodies of public declarations but excludes private
ones. Editing the body of a `private def` therefore leaves
`M.olean.hash` unchanged, and downstream modules cache-hit.

`REPORT.md` walks through an empirical demonstration on
`Mathlib.Data.TwoPointing`. Mathlib4 PR
[#38702](https://github.com/leanprover-community/mathlib4/pull/38702)
applied this lever to ~30 declarations in the real-numbers cluster.
This pipeline generalises that approach: find every declaration where
the same lever applies.

## Running the pipeline

Prerequisites:

- A mathlib4 worktree somewhere on disk; `MATHLIB_DIR` defaults to
  `$HOME/mathlib4`.
- Python 3.11+ with `networkx` and `pytest`.
- `elan` for the census step (Lean 4 toolchain).

End-to-end refresh:

```bash
# Full census + downstream artefacts (~45 minutes).
bash pipeline/scripts/snapshot.sh

# Same, but reuse the existing census (~30 seconds).
SKIP_CENSUS=1 bash pipeline/scripts/snapshot.sh
```

The snapshot writes:

- `data/census_lean.jsonl.gz` — output of the Lean census.
- `data/ranked_candidates.jsonl.gz` — output of the Python re-ranker.
- `data/estimated_impact.json` — CP-s impact per top-N privatization
  set, against the last 1,500 mathlib master commits.
- `data/snapshots/{census,impact}_<DATE>.json[.gz]` — date-stamped copy.
- `site/index.html` — regenerated dashboard.

Applying privatizations to mathlib (does NOT run by default; the scripts
mutate a mathlib worktree):

```bash
# Bulk: apply all tier-1 candidates as a single commit, then converge.
python3 pipeline/src/bulk_apply.py
(cd "$MATHLIB_DIR" && git add -A && git commit -m "WIP: bulk privatize")
bash pipeline/scripts/bulk_iterate.sh

# Per-bundle: one commit per module, with importer-cap verification.
bash pipeline/scripts/iterate_bundle.sh Mathlib.Tactic.Ring.Basic
```

## Documentation

- [`docs/design.md`](docs/design.md): rationale for the pipeline shape;
  what `private` does mechanically; the two operating modes.
- [`docs/methodology.md`](docs/methodology.md): the selection
  heuristic, the policy hierarchy, and the per-module scoring formula.
- [`docs/results.md`](docs/results.md): outcomes of running the
  pipeline against current mathlib.
- [`docs/pr-38702-trace.md`](docs/pr-38702-trace.md): per-decl trace
  showing which of PR 38702's 40 privatized declarations the
  pipeline surfaces and why the others do not.
- [`docs/cache-cut-empirics.md`](docs/cache-cut-empirics.md): an
  empirical hash-table demonstrating the cache-cut on
  `Mathlib.Data.TwoPointing`.

The dashboard (`site/index.html`) embeds a Methodology tab that covers
the same material as `docs/methodology.md`.

## Layout

```
mathlib-hide-decls/
├── README.md                this file
├── LICENSE                  Apache 2.0
├── docs/
│   ├── design.md            pipeline design rationale
│   ├── methodology.md       selection + scoring
│   ├── results.md           current results
│   ├── pr-38702-trace.md    per-decl trace against PR 38702
│   └── cache-cut-empirics.md   empirical demonstration
├── census/                  standalone Lean project
│   ├── README.md
│   ├── lakefile.lean        pins mathlib4 at a master commit
│   ├── lean-toolchain
│   ├── DeclCensus.lean      meta-program library
│   ├── Main.lean            full-mathlib entry point
│   └── test/
│       ├── Small.lean       Mathlib.Logic.Basic fixture
│       └── Simps.lean       @[simps]-using fixture
├── pipeline/
│   ├── policy.toml          single source of truth for filter policy
│   ├── src/
│   │   ├── paths.py         path resolution
│   │   ├── policy.py        policy.toml loader + parse_attrs
│   │   ├── rerank.py        tier 1/2/3 binner
│   │   ├── bulk_apply.py    apply private to all tier-1 in one pass
│   │   ├── bulk_revert.py   build-log error parser + reverter
│   │   ├── iterate_bundle.sh  per-module: apply + verify + commit
│   │   ├── triage_module.py  helper used by iterate_bundle
│   │   ├── estimate_impact.py  CP-s impact estimator
│   │   └── build_dashboard.py   HTML generator
│   ├── scripts/
│   │   ├── snapshot.sh      one-command refresh
│   │   ├── bulk_iterate.sh  bulk pipeline driver
│   │   ├── iterate_bundle.sh  per-bundle pipeline driver
│   │   └── cache_demo.sh    empirical cache-cut demo
│   └── tests/               pytest suites (28 tests)
├── data/
│   ├── census_lean.jsonl.gz       ~350K decls × 14 fields
│   ├── ranked_candidates.jsonl.gz ~26K candidates with tier
│   ├── churn_blast.json           per-module blast cone + edit history
│   ├── lakeprof.graph.json.gz     mathlib import graph with build times
│   ├── estimated_impact.json      CP-s impact per top-N set
│   └── snapshots/                 dated archives
├── site/index.html          generated dashboard
└── .github/workflows/       CI: tests, pages, manual census
```

## License

Apache 2.0. See `LICENSE`.
