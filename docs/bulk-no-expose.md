# Bulk @[no_expose] / private experiment

A single-commit batch of `@[no_expose]` (on defs) and `private` (on
theorems / lemmas) applied across every module that hosts a top-K
tier-3 hub, prioritized by hub score. The tier-3 analog of the tier-1
bulk pipeline (`bulk_apply.py`), adapted for the new Lean 4 module
system's body-hiding tools.

The producing pipeline is `pipeline/scripts/bulk_no_expose_iterate.sh`,
which orchestrates `bulk_no_expose_apply.py` (initial mass-apply) and
`bulk_no_expose_revert.py` (build → revert loop). See
[`methodology.md` §5b](methodology.md#5b-encap-mechanics-in-the-new-lean-4-module-system)
for the per-decl choice rule between `private` and `@[no_expose]`.

## Run shape

1. **Seed**: top-K tier-3 hubs by score (default K=1000 via
   `BULK_NO_EXPOSE_TOP_K`). Their unique defining modules are the
   target set.
2. **Apply pass** (`bulk_no_expose_apply.py`):
   - For every `def` in a target module: `@[no_expose]` inserted as a
     new line directly above the keyword (under any modifier lines).
   - For every `theorem` / `lemma` in a target module: `private`
     prefixed on the keyword line.
   - Skipped: decls carrying `@[match_pattern]`, `@[simp]`,
     `@[simps]`, `@[ext]`, `@[instance]`, `@[coe]`, `@[to_additive]`,
     `@[to_dual]`, `@[push]`, the elaborator-extension family
     (`@[macro]`, `@[macro_rules]`, `@[tactic]`, `@[elab_rules]`,
     `@[term_parser]`, `@[builtin_*]`, …), the policy.toml hard-block
     set (`@[reducible]`, `@[implicit_reducible]`, `@[inline]`,
     `@[deprecated]`), and decls whose preceding attribute block has
     unbalanced brackets (multi-line `@[to_dual\n…/-- … -/]`).
   - Also skipped: decls bound to user notation in the same file
     (the notation table records the bare name; can't resolve
     mangled forms cross-module).
3. **Initial commit** on
   `experiment/bulk-no-expose-<timestamp>` (branched from
   `origin/master`).
4. **Build + revert loop**:
   - `lake build` on the whole repo.
   - If it passes, the bulk run amends the commit with the final
     retained count and exits.
   - If it fails, `bulk_no_expose_revert.py` parses the log:
     - **Direct decl-name matches** in errors (`Unknown constant`,
       `Invalid field`, `Invalid rewrite argument`,
       `Compilation failed, locally inferred compilation type
       differs … definitions may need to be @[expose]'d: NAME …`)
       map directly to manifest entries and revert them.
     - **Site-proximity revert**: each `error: PATH:LINE:` site
       reverts every manifest entry in that file with
       `line_inserted_at` within ±10 of LINE.
     - **Whole-file revert**: every manifest entry in every file
       that had ANY error is reverted, regardless of proximity.
       This is the convergence-friendly fallback for cross-file
       semantic cascades (`Not a definitional equality`) where the
       upstream cause isn't named in the error.
   - The commit is amended with the file changes, and the loop
     continues.
5. **Convergence**: either the build passes (success — single
   commit with maximal retained set) or `ITER_CAP` iterations (default
   30) elapse without convergence (failure — partial commit, branch
   left for inspection).

## Latest run (TOP_K=100, 2026-05-12)

| metric | value |
|---|---:|
| Top-K hub seed | 100 |
| Modules touched (initial apply) | 75 |
| Decls applied (initial) | 2,726 (`private` on 1,121 theorems + `@[no_expose]` on 1,605 defs) |
| Decls retained after auto-iterate | 109, across 5 files |
| Decls retained after manual wholesale-revert of 5 stuck files | **2** |
| Iterations to converge | 18 (auto) + 5 manual wholesale-reverts |
| Branch | [`experiment/bulk-no-expose-20260512-0909`](https://github.com/marcelolynch/mathlib4/tree/experiment/bulk-no-expose-20260512-0909) on `marcelolynch/mathlib4` |
| `lake build` final status | passes (8,395 jobs) |

### The 2 surviving retentions

Both are in `Mathlib/Tactic/Module.lean`, on meta-defs inside a
`public meta section`:

- `@[no_expose] meta def qNF.add`
- `@[no_expose] meta def qNF.mkAddProof`

These survived because they're compile-time code — they have no
type-elaboration users in downstream files, so the cross-file
cascade pattern that wiped the other 2,724 doesn't apply.

### Why the yield is so low

The iterate-revert loop converged to 109 retentions across 5 hot files
(`UniformSpace/Equicontinuity.lean`, `GroupTheory/Perm/Fin.lean`,
`AlgebraicGeometry/PullbackCarrier.lean`, `Tactic/FieldSimp.lean`,
`RingedSpace/LocallyRingedSpace/ResidueField.lean`). The remaining 21
build errors clustered in files that *consume* those modules
(`Topology/UniformSpace/Ascoli.lean`,
`GroupTheory/SpecificGroups/Alternating.lean`,
`AlgebraicGeometry/ResidueField.lean`,
`Topology/ContinuousMap/Bounded/ArzelaAscoli.lean`,
`Analysis/CStarAlgebra/CStarMatrix.lean`).

Those consumer errors were all of forms that don't name a culprit
constant: `Type mismatch`, `Function expected`, `Invalid simp theorem
Equicontinuous: Expected a definition with an exposed body`,
`Tactic decide failed`. The revert script can pinpoint upstream
culprits when the error names a constant
(`Unknown identifier`, `Unknown constant`, etc.) — but semantic
errors that leak through dot-method dispatch, typeclass-resolution
unfolding, or `simp` lemma elaboration leave no breadcrumb. The
remedy of "revert all entries in the failing file" doesn't help
either, because the failing files in these cases were the
downstream consumers, not the producers.

### Design lessons

- **Cross-file cascades dominate large-K runs.** With K=100 each
  module is touched in isolation; once the touched modules' decls
  propagate into downstream files via dot-method / typeclass /
  simp-rewrite mechanisms, the iterate-revert loop loses its ability
  to localise the cause.
- **A per-file isolation mode would converge better.** Apply to one
  module, build, keep iff the build passes, otherwise revert that
  module. Each retained edit is then individually validated. The
  bulk pipeline as designed trades this granularity for "single
  commit" semantics; the trade is unfavourable when consumers don't
  belong to the seed module set.
- **The K=100 retained set isn't the maximal-passing set.** The
  manual wholesale-revert of the 5 hot files threw out 109 retained
  edits, some of which might individually pass. A bisection on those
  could likely recover a non-trivial fraction.

### What's actionable

The bulk pipeline (`pipeline/scripts/bulk_no_expose_iterate.sh` and its
`apply` / `revert` companions) remains useful as the *engine* — it
correctly applies, correctly reverts on namable errors, and converges
in finite iterations. Future runs should:

1. Run with smaller K (e.g. 10–30) to reduce cross-file cascade risk.
2. Add a per-module isolation step before the global build, so
   modules whose edits don't even compile in isolation get pruned
   before the global iterate.
3. Sequence as: per-module verify → batch global build → bisect on
   any cross-file cascades.

