# Results

Outcomes of running the pipeline against current mathlib master.

## Bulk pipeline

Applies every tier-1 candidate in one commit, then loops
build → revert → amend until convergence.

| metric | value |
|---|---:|
| Mathlib declarations scanned | 349,712 |
| Tier-1 candidates (current ranking) | **8,124** |
| Tier-2 module bundles (current ranking) | **718** |
| Tier-3 hub candidates (current ranking) | **25,418** |

The numbers below are from the last full bulk-pipeline run, which used
the previous Tier-1 rule (`n_intra_module_refs == 0`, 4,269 candidates).
The refined rule (`n_signature_refs == 0`, 8,124 candidates) has not
been validated end-to-end yet; the next run will produce updated
retention figures.

| metric (previous run) | value |
|---|---:|
| Tier-1 candidates at the time | 4,269 |
| Mechanically applicable to a `def`/`theorem`/`lemma` line | 2,148 |
| Files touched by the initial commit | 953 |
| Reverts applied during iteration | ~555 |
| **Privatizations retained at convergence** | **1,547** |
| Files modified at convergence | 749 |
| **Retention** | **72.0% of applied candidates** |
| `lake build` status | passes end-to-end (8,386 / 8,386 jobs) |

Branch on the maintainer's fork:
`experiment/bulk-tier1` on
[`marcelolynch/mathlib4`](https://github.com/marcelolynch/mathlib4/tree/experiment/bulk-tier1).

### Top 10 modules by retained privatizations

| `+private` | file |
|---:|---|
| 29 | `Mathlib/Combinatorics/SimpleGraph/Walk/Operations.lean` |
| 26 | `Mathlib/Combinatorics/SimpleGraph/Paths.lean` |
| 23 | `Mathlib/Geometry/Euclidean/Incenter.lean` |
| 22 | `Mathlib/Combinatorics/SimpleGraph/Clique.lean` |
| 20 | `Mathlib/Combinatorics/SimpleGraph/Maps.lean` |
| 19 | `Mathlib/Combinatorics/SimpleGraph/Connectivity/Subgraph.lean` |
| 18 | `Mathlib/Combinatorics/SimpleGraph/Diam.lean` |
| 18 | `Mathlib/Combinatorics/SimpleGraph/Connectivity/Connected.lean` |
| 16 | `Mathlib/Combinatorics/SimpleGraph/Coloring/VertexColoring.lean` |
| 14 | `Mathlib/Combinatorics/SimpleGraph/Metric.lean` |

Eight of the top ten retained-priv files are `SimpleGraph.*`.
Combinatorics modules are API-rich, lemma-heavy, and modular: most
small lemmas are internal helpers, which the policy correctly
identifies. Geometry and AlgebraicTopology show similar but smaller
concentrations.

### Top 10 modules by revert count

| reverts | file |
|---:|---|
| 37 | `Mathlib/Combinatorics/SimpleGraph/Subgraph.lean` |
| 29 | `Mathlib/Tactic/Positivity/Basic.lean` |
| 21 | `Mathlib/Tactic/NormNum/Basic.lean` |
| 17 | `Mathlib/Tactic/TacticAnalysis/Declarations.lean` |
| 16 | `Mathlib/Geometry/Euclidean/Incenter.lean` |
| 14 | `Mathlib/AlgebraicTopology/SimplexCategory/Basic.lean` |
| 10 | `Mathlib/Combinatorics/SimpleGraph/Maps.lean` |
|  8 | `Mathlib/Tactic/NormNum/Ordinal.lean` |
|  8 | `Mathlib/CategoryTheory/Limits/Shapes/BinaryProducts.lean` |
|  8 | `Mathlib/Combinatorics/SimpleGraph/AdjMatrix.lean` |

The `Mathlib.Tactic.*` clusters are addressed by the
`forbidden_module_prefixes` filter (`methodology.md §2`), which moves
them out of tier-1 before apply. The Combinatorics modules in this
list are mixed cases: high apply counts trigger more reverts in
absolute terms even when the per-decl revert rate is low.

## Per-bundle pipeline

The per-bundle pipeline runs `iterate_bundle.sh` against one module
at a time, with a 4-importer build cap before committing. Output: a
series of small per-module commits, each independently reviewable.

A 100-commit run produced 394 privatizations across 100 files,
including 3 top-30 leverage modules. After a global verification
pass (full-mathlib build of the merged accumulator branch), 11
commits were reverted: 8 due to `Simps.*` projections breaking
downstream `@[simps]`-derived simp lemmas, 3 due to dot-method
elaboration from outside the 4-importer cap. Final retention:
100/111 commits (90.1%), 394/432 privs (91.2%).

## Where the pipeline does and does not apply

Empirically, the hypothesis "this decl is internal" holds robustly
in API-rich, lemma-heavy, modular subsystems:

1. **Combinatorics** (especially `SimpleGraph.*`). Top retained list
   above; the highest yield concentration in mathlib.
2. **Geometry** (`Geometry/Euclidean/Incenter.lean`,
   `AlgebraicTopology/SimplexCategory/*`). Same shape with smaller
   per-module counts.
3. **General algebra** (`RingTheory.*`, `LinearAlgebra.*`,
   `Topology.*`). Higher friction per module, but each retained
   privatization tends to have a larger downstream cache-cut benefit
   because these modules sit deeper in the import graph.

Categories the policy filters out:

- **Decls registering into an extension by name**: `policy.toml`'s
  `build_rejected_attrs` catches the standard set
  (`simp`, `norm_cast`, `ext`, `macro`, `fun_prop`, `positivity`,
  `norm_num`, `simps`, `instance`, `coe`, `gcongr`, `mono`,
  `aesop`, `push_cast`, `decide`, `to_additive`, `elab_rules`,
  `term_parser`, `builtin_*`, `tactic`, `macro_rules`).
- **Decls under a `@[simps]`-emitting parent**: caught by the
  `simps_projection` name pattern and the namespace-prefix fallback
  in the revert ladder.
- **Custom class instances built via `@[mk_eval]`-style macros**:
  caught by the `(kernel) declaration has metavariables 'X'`
  pattern, which triggers a namespace-prefix sweep.
- **Decls referenced via dot-method dispatch from outside the
  4-importer cap**: caught only at the final full-mathlib build. The
  bulk pipeline handles these via the iterate-revert loop; the
  per-bundle pipeline's global verification step catches them after
  the fact.
- **`Mathlib.Tactic.**` and `Mathlib.Meta.**`**: dropped by the
  `forbidden_module_prefixes` filter. These directories are
  dominated by elaborator helpers that register themselves into
  extension state by name.

## Estimated rebuild-CP impact

From `data/estimated_impact.json`, computed against the last 1,500
mathlib master commits:

- Bulk-pipeline retention set (~1,547 privs, top-30 weighted):
  ~64,000 CP-seconds saved per 1,500-commit window, ≈ 43 full-mathlib
  critical-path builds avoided per month, ≈ 520 builds per year on
  the master CI.
- Per-bundle 100-commit run (394 privs across 100 files):
  ~64,000 CP-seconds saved per 1,500-commit window, ≈ 43 builds
  saved per month.

These estimates depend on the blast cone shape of each module and
the editing frequency over the window. Modules edited only once in
the window contribute zero to the estimate even if their cascade is
expensive.

## Calibration against PR 38702

The dashboard cites mathlib4 PR
[#38702](https://github.com/leanprover-community/mathlib4/pull/38702)
as the canonical worked example of sub-module encapsulation. The PR
privatizes 40 decls organised around 4 hubs. The pipeline surfaces 3
hubs (`Real.mk`, `Real.ofCauchy`, `Real.equivCauchy`) as Tier 3,
reaching **24 of 40** decls through their Co-located columns. The
remaining 16 are 13 anchored to `Real.cauchy` (blocked by
`@[reducible]`), 2 bridging lemmas with no structural hub, and 1
elaborated away before the meta-program sees it.

[`pr-38702-trace.md`](pr-38702-trace.md) has the per-decl table and
the history of how coverage has changed across ranker iterations.

## Live numbers

Current candidate counts and per-snapshot transitions live in the
dashboard's Run history view at `site/index.html`. Each
`pipeline/scripts/snapshot.sh` run appends one row.
