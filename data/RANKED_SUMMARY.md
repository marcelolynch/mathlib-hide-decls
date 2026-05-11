# Ranked candidate queue (Lean census)

_Generated from `census_lean.jsonl` (349,712 decls)._

Three tiers, in priority order. Apply the corrected policy from the
framework note: defs/abbrevs hide more freely; theorems only with strong
intent signals (no docstring + internal name pattern); encapsulation
clusters get their own tier for human review.

## Headline numbers

- **8,124** tier-1 solo candidates (mech-hidable AND intent-safe)
- **718** tier-2 module bundles (group tier-1 by module, ≥3 decls)
- **12,382** tier-3 encapsulation hubs (PR-38702-shape, human review)

## Tier 1 — solo intent-safe candidates (top 25 by module score)

| score | kind | pattern | docstr | module / decl |
|---:|---|---|:---:|---|
| 6.0 | def | normal | Y | `Ordinal.termω` |
| 6.0 | def | normal | Y | `Cardinal.gciOrdCard` |
| 6.0 | def | normal | Y | `Ordinal.termTypeLT_` |
| 5.6 | def | normal | Y | `Ordinal.pred_succ_gi` |
| 5.3 | def | normal | Y | `NNReal.«termℝ≥0»` |
| 5.3 | theorem | aux | . | `List.map_reverseAux` |
| 5.3 | def | normal | Y | `Mathlib.Meta.Positivity.evalNNRealtoReal` |
| 5.3 | def | normal | Y | `Mathlib.Meta.Positivity.evalRealNNAbs` |
| 5.3 | def | normal | Y | `NNReal.gi` |
| 5.3 | def | normal | Y | `Mathlib.Meta.Positivity.evalRealToNNReal` |
| 5.2 | def | normal | Y | `Cardinal.«term_^<_»` |
| 5.1 | theorem | aux | . | `MonoidAlgebra.single_mul_apply_aux` |
| 5.1 | def | normal | Y | `AddMonoidAlgebra.unexpander` |
| 5.1 | def | normal | Y | `LibraryNote.«fact_non-instances»` |
| 5.1 | def | normal | Y | `Exists.classicalRecOn` |
| 5.1 | def | normal | Y | `MonoidAlgebra.«term__[_]»` |
| 5.1 | theorem | aux | . | `MonoidAlgebra.mul_single_apply_aux` |
| 5.1 | def | normal | Y | `AddMonoidAlgebra.«term__[_]»` |
| 5.1 | def | normal | Y | `Classical.byContradiction'` |
| 5.1 | def | normal | Y | `Classical.existsCases` |
| 5.1 | def | normal | Y | `MonoidAlgebra.mul'` |
| 5.1 | def | normal | Y | `LibraryNote.decidable_namespace` |
| 5.1 | def | normal | Y | `LibraryNote.decidable_arguments` |
| 5.1 | def | normal | Y | `MonoidAlgebra.unexpander` |
| 4.9 | def | normal | Y | `Subring.gi` |

## Tier 2 — module bundles (top 25 by total impact)

Each bundle is one mechanical PR. Cap at 80 decls per PR; modules with more get split.

| score | n_decls | T30 | edits | module |
|---:|---:|:---:|---:|---|
| 144.0 | 146 | . | - | `Mathlib.AlgebraicTopology.SimplicialObject.Basic` |
| 120.0 | 120 | . | - | `Mathlib.MeasureTheory.Function.SimpleFunc` |
| 109.6 | 143 | . | - | `Mathlib.Combinatorics.SimpleGraph.Subgraph` |
| 81.0 | 105 | . | - | `Mathlib.Combinatorics.SimpleGraph.Walk.Operations` |
| 73.0 | 87 | . | - | `Mathlib.Combinatorics.SimpleGraph.Maps` |
| 57.8 | 78 | . | - | `Mathlib.Combinatorics.SimpleGraph.Paths` |
| 57.0 | 57 | . | - | `Mathlib.LinearAlgebra.AffineSpace.Simplex.Basic` |
| 56.7 | 95 | . | - | `Mathlib.Combinatorics.SimpleGraph.Clique` |
| 54.5 | 55 | . | - | `Mathlib.AlgebraicTopology.SimplexCategory.Basic` |
| 48.2 | 52 | . | - | `Mathlib.AlgebraicTopology.SimplicialSet.StdSimplex` |
| 47.1 | 52 | . | - | `Mathlib.Combinatorics.SimpleGraph.Basic` |
| 44.0 | 44 | . | - | `Mathlib.MeasureTheory.Function.SimpleFuncDenseLp` |
| 43.9 | 74 | . | - | `Mathlib.Combinatorics.SimpleGraph.Connectivity.Connected` |
| 42.8 | 66 | . | - | `Mathlib.Combinatorics.SimpleGraph.Copy` |
| 39.2 | 47 | . | - | `Mathlib.Combinatorics.SimpleGraph.Finite` |
| 39.0 | 39 | . | - | `Mathlib.MeasureTheory.Integral.SetToL1` |
| 35.6 | 7 | Y | 7 | `Mathlib.Algebra.MonoidAlgebra.Defs` |
| 33.8 | 43 | . | - | `Mathlib.Combinatorics.SimpleGraph.Walk.Basic` |
| 30.5 | 6 | Y | 7 | `Mathlib.Logic.Basic` |
| 30.0 | 30 | . | - | `Mathlib.MeasureTheory.Integral.Bochner.L1` |
| 29.0 | 29 | . | - | `Mathlib.Data.List.Permutation` |
| 28.6 | 38 | . | - | `Mathlib.Combinatorics.SimpleGraph.Walk.Decomp` |
| 26.5 | 5 | Y | 9 | `Mathlib.Data.NNReal.Defs` |
| 25.0 | 67 | . | - | `Mathlib.Combinatorics.SimpleGraph.Connectivity.Subgraph` |
| 24.8 | 25 | . | - | `Mathlib.Geometry.Manifold.Notation` |

## Tier 3 — encapsulation hubs (top 25 by score)

Each hub is a candidate for the PR-38702 refactor pattern: privatize the
hub def + the lemmas whose signatures reference it; extract to a sub-module
if needed; have the (≤30) external consumers `public import` the sub-module.

| score | sig_refs | ext_users | docstr | module / hub |
|---:|---:|---:|:---:|---|
| 125.2 | 60 | 2 | Y | `Order.cof` |
| 111.4 | 63 | 2 | Y | `Order.IsPredLimit` |
| 107.1 | 19 | 0 | Y | `Ordinal.pred` |
| 95.8 | 96 | 0 | Y | `ValuativeRel.vlt` |
| 85.8 | 172 | 1 | Y | `ValuativeRel.vle` |
| 80.0 | 178 | 0 | Y | `MulArchimedeanClass` |
| 74.7 | 75 | 0 | Y | `CategoryTheory.Functor.mapAddGrp` |
| 74.3 | 95 | 7 | Y | `Ordinal.cof` |
| 74.2 | 15 | 0 | Y | `Subring.prod` |
| 71.0 | 71 | 0 | Y | `AddSubsemigroup.map` |
| 66.0 | 66 | 0 | Y | `CommRingCat.Colimits.ColimitType` |
| 65.0 | 65 | 0 | Y | `RingCat.Colimits.ColimitType` |
| 64.1 | 71 | 0 | Y | `AlgebraicGeometry.Scheme.IdealSheafData.glueDataObj` |
| 62.1 | 79 | 0 | Y | `Algebra.Presentation.Core` |
| 60.6 | 61 | 0 | Y | `IsIdempotentElem.Corner` |
| 60.5 | 61 | 0 | Y | `AlgebraicGeometry.Scheme.Pullback.gluing` |
| 60.0 | 60 | 0 | Y | `Mathlib.Tactic.Module.NF` |
| 59.0 | 89 | 7 | Y | `Order.IsPredPrelimit` |
| 58.0 | 58 | 0 | Y | `Subgroup.ofUnits` |
| 55.4 | 144 | 1 | Y | `CategoryTheory.Center` |
| 55.0 | 110 | 1 | Y | `SetSemiring` |
| 55.0 | 55 | 0 | Y | `AddSubgroup.ofAddUnits` |
| 53.0 | 53 | 0 | Y | `AddSubsemigroup.comap` |
| 53.0 | 53 | 0 | Y | `Mathlib.Tactic.FieldSimp.qNF.toNF` |
| 52.9 | 53 | 0 | Y | `ValuativeRel.ValueGroupWithZero.mk` |
