# PR 38702 trace

Mathlib4 PR
[#38702](https://github.com/leanprover-community/mathlib4/pull/38702)
(`chore(Data/Real): encapsulate real numbers`) is cited in the
dashboard as the canonical worked example of sub-module
encapsulation. The PR is currently open; this trace records, against
the latest census, which of its decls the pipeline surfaces and why
the rest do not.

The pipeline is intentionally more conservative than PR 38702's
author: most of the PR's decls would not be flagged by our tiering
even though the author chose to privatize them. This document is the
audit trail for that gap.

## What PR 38702 privatizes

The PR diff adds `private` to 40 declarations under
`Mathlib.Data.Real.Basic`. The split:

| kind | count |
|---|---:|
| `def` | 2 (`Real.equivCauchy`, `Real.mk`) |
| `theorem` / `lemma` | 38 (the `cauchy_*`, `ofCauchy_*`, `mk_*`, and `ext_cauchy*` families) |

Of those 40, **39 are present in `data/census_lean.jsonl.gz`** at the
pinned mathlib commit (`Real.sub_def` does not appear; the kernel
elaborates the subtraction defining equation away before the census
sees it).

## What the pipeline surfaces

One: `Real.mk` (Tier 3).

```jsonc
{
  "tier": "3_encap",
  "fq_name": "Real.mk",
  "kind": "def",
  "n_signature_refs": 26,
  "n_external_users": 1,
  "n_intra_module_refs": 41,
  "score": 13.0
}
```

The Tier-3 row's `Co-located decls` column lists the same-module
declarations that reference `Real.mk` in their type signature, which
is exactly the set of dependents that move with `Real.mk` under
sub-module encapsulation. The top user-facing entries:

```
Real.mk_le_of_forall_le    Real.le_mk_of_forall_le    Real.mk_one
Real.mk_lt                 Real.mk_mul                Real.mk_add
Real.mk_const              Real.ind_mk                Real.mk_zero
Real.mk_inf                Real.mk_eq                 Real.mk_sup
Real.mk_near_of_forall_near Real.mk_neg               Real.mk_le
Real.mk_pos
```

That is, the pipeline does flag the `Real.mk` cluster — as a single
hub row plus its dependents — and the action it suggests is precisely
the move PR 38702 makes for that hub. The pipeline differs from the
PR only on the other 38 decls.

## Why the other 38 do not surface

The decls fall into four buckets, each corresponding to a specific
filter in the policy or tiering rules.

### Bucket 1: theorems with `n_intra_module_refs > 0` (30 decls)

The Tier-1 rule for `def`/`abbrev` is `n_external_users == 0 AND
n_intra_module_refs == 0`. The same gate applies to internal-pattern
theorems. Inside `Mathlib.Data.Real.Basic` the `cauchy_zero`,
`mk_add`, `ofCauchy_neg`, etc. theorems reference each other (and
reference base definitions like `Real.cauchy`), so each one has
non-zero intra-module references.

Examples:

| decl | `n_intra_module_refs` |
|---|---:|
| `Real.ext_cauchy` | 16 |
| `Real.cauchy_add` | 10 |
| `Real.cauchy_mul` | 9 |
| `Real.cauchy_zero` | 6 |
| `Real.mk_le` | 6 |
| `Real.mk_lt` | 4 |
| `Real.ofCauchy_zero` | 3 |
| `Real.cauchy_one` | 3 |
| `Real.mk_one` | 0 (would qualify if not for bucket 2 below) |

The Tier-1 gate exists because privatizing one decl in a
cross-referencing cluster breaks the cluster's siblings. PR 38702
moves them all together into a sub-module so the cluster's
visibility is closed; our tiering policy doesn't recognise that
as a single action, only the individual decls.

### Bucket 2: theorems with `name_pattern=normal` and no docstring (7 decls)

The Tier-1 intent gate refuses theorems that lack any
"intended-internal" signal: a theorem with `name_pattern=normal` is
treated as public API even when its reference counts permit
privatization. The gate accepts theorems only when
`name_pattern ∈ {underscore_prefix, aux, internal_namespace}` or the
decl has a docstring marker explicitly tagging it as internal.

The decls in this bucket have `n_external_users == 0`,
`n_intra_module_refs == 0`, no docstring, and `name_pattern=normal`:

```
Real.cauchy_intCast    Real.cauchy_natCast    Real.cauchy_nnratCast
Real.cauchy_ratCast    Real.cauchy_inv        Real.cauchy_sub
Real.ofCauchy_sub      Real.of_near           Real.mk_one
```

The gate prefers false negatives over false positives because
mis-privatizing a theorem that users depend on is a more expensive
mistake than failing to suggest a privatization.

### Bucket 3: `def` with `n_signature_refs < 5` (1 decl)

`Real.equivCauchy`. The Tier-3 rule requires `n_signature_refs ≥ 5`
on the assumption that smaller dependent clusters do not justify the
import-graph churn of a sub-module split. `Real.equivCauchy` has
`n_signature_refs == 2`, with `n_external_users == 1` and
`n_intra_module_refs == 3`.

The PR's author chose to extract it anyway because it is structurally
part of the broader Real-numbers encapsulation, not because it
independently meets a high-dependency threshold.

### Bucket 4: theorem with `n_external_users > 0` (1 decl)

`Real.ind_mk` has 15 intra-module references and 1 external user.
Either one disqualifies it from Tier 1. The PR privatizes it on the
basis that the single external user is itself an
encapsulation-internal helper that moves into the new sub-module
along with `ind_mk`, but this requires resolving the dependency at
the cluster level, not the per-decl level.

## Full per-decl trace

The complete classification of all 40 PR-38702 decls against the
current census + policy:

| decl | kind | `n_ext` | `n_intra` | `n_sig` | doc | pattern | attrs | verdict |
|---|---|---:|---:|---:|:-:|---|---|---|
| `Real.mk` | def | 1 | 41 | 26 | Y | normal | — | **Tier 3** |
| `Real.equivCauchy` | def | 1 | 3 | 2 | Y | normal | — | bucket 3 (n_sig_refs<5) |
| `Real.sub_def` | — | — | — | — | — | — | — | absent from census |
| `Real.cauchy_add` | theorem | 0 | 10 | 0 | · | normal | — | bucket 1 (n_intra=10) |
| `Real.cauchy_inv` | theorem | 0 | 0 | 0 | · | normal | — | bucket 2 (no intent) |
| `Real.cauchy_intCast` | theorem | 0 | 0 | 0 | · | normal | — | bucket 2 |
| `Real.cauchy_mul` | theorem | 0 | 9 | 0 | · | normal | — | bucket 1 (n_intra=9) |
| `Real.cauchy_natCast` | theorem | 0 | 0 | 0 | · | normal | — | bucket 2 |
| `Real.cauchy_neg` | theorem | 0 | 3 | 0 | · | normal | — | bucket 1 (n_intra=3) |
| `Real.cauchy_nnratCast` | theorem | 0 | 0 | 0 | · | normal | — | bucket 2 |
| `Real.cauchy_one` | theorem | 0 | 3 | 0 | · | normal | — | bucket 1 (n_intra=3) |
| `Real.cauchy_ratCast` | theorem | 0 | 0 | 0 | · | normal | — | bucket 2 |
| `Real.cauchy_sub` | theorem | 0 | 0 | 0 | · | normal | — | bucket 2 |
| `Real.cauchy_zero` | theorem | 0 | 6 | 0 | · | normal | — | bucket 1 (n_intra=6) |
| `Real.ext_cauchy` | theorem | 0 | 16 | 0 | · | normal | — | bucket 1 (n_intra=16) |
| `Real.ext_cauchy_iff` | theorem | 0 | 2 | 0 | · | normal | — | bucket 1 (n_intra=2) |
| `Real.ind_mk` | theorem | 1 | 15 | 0 | · | normal | — | bucket 4 (n_ext=1) |
| `Real.isCauSeq_iff_lift` | theorem | 0 | 1 | 0 | · | normal | — | bucket 1 (n_intra=1) |
| `Real.mk_add` | theorem | 0 | 1 | 0 | · | normal | — | bucket 1 (n_intra=1) |
| `Real.mk_const` | theorem | 0 | 2 | 0 | · | normal | — | bucket 1 (n_intra=2) |
| `Real.mk_eq` | theorem | 0 | 2 | 0 | · | normal | — | bucket 1 (n_intra=2) |
| `Real.mk_le` | theorem | 0 | 6 | 0 | · | normal | — | bucket 1 (n_intra=6) |
| `Real.mk_lt` | theorem | 0 | 4 | 0 | · | normal | — | bucket 1 (n_intra=4) |
| `Real.mk_mul` | theorem | 0 | 1 | 0 | · | normal | — | bucket 1 (n_intra=1) |
| `Real.mk_neg` | theorem | 0 | 1 | 0 | · | normal | — | bucket 1 (n_intra=1) |
| `Real.mk_one` | theorem | 0 | 0 | 0 | · | normal | — | bucket 2 (no intent) |
| `Real.mk_pos` | theorem | 0 | 1 | 0 | · | normal | — | bucket 1 (n_intra=1) |
| `Real.mk_zero` | theorem | 0 | 1 | 0 | · | normal | — | bucket 1 (n_intra=1) |
| `Real.ofCauchy_add` | theorem | 0 | 2 | 0 | · | normal | — | bucket 1 (n_intra=2) |
| `Real.ofCauchy_intCast` | theorem | 0 | 1 | 0 | · | normal | — | bucket 1 (n_intra=1) |
| `Real.ofCauchy_inv` | theorem | 0 | 2 | 0 | · | normal | — | bucket 1 (n_intra=2) |
| `Real.ofCauchy_mul` | theorem | 0 | 3 | 0 | · | normal | — | bucket 1 (n_intra=3) |
| `Real.ofCauchy_natCast` | theorem | 0 | 2 | 0 | · | normal | — | bucket 1 (n_intra=2) |
| `Real.ofCauchy_neg` | theorem | 0 | 2 | 0 | · | normal | — | bucket 1 (n_intra=2) |
| `Real.ofCauchy_nnratCast` | theorem | 0 | 1 | 0 | · | normal | — | bucket 1 (n_intra=1) |
| `Real.ofCauchy_one` | theorem | 0 | 3 | 0 | · | normal | — | bucket 1 (n_intra=3) |
| `Real.ofCauchy_ratCast` | theorem | 0 | 2 | 0 | · | normal | — | bucket 1 (n_intra=2) |
| `Real.ofCauchy_sub` | theorem | 0 | 0 | 0 | · | normal | — | bucket 2 (no intent) |
| `Real.ofCauchy_zero` | theorem | 0 | 3 | 0 | · | normal | — | bucket 1 (n_intra=3) |
| `Real.of_near` | theorem | 0 | 0 | 0 | · | normal | — | bucket 2 (no intent) |

Summary:

| bucket | count |
|---|---:|
| Surfaced as Tier 3 | 1 |
| Bucket 1: theorem with `n_intra_module_refs > 0` | 30 |
| Bucket 2: theorem with `name_pattern=normal`, no docstring | 7 |
| Bucket 3: def with `n_signature_refs < 5` | 1 |
| Bucket 4: theorem with `n_external_users > 0` | 1 |
| Absent from census | 1 |
| **Total** | **40** |

## Implications

The pipeline finds **1** of the 40 PR-38702 decls. That is the
expected behaviour given the policy as written, not a bug.

What it does mean:

1. **The pipeline does not reproduce PR-38702-style cluster moves.**
   The Tier-1 gate's strict "0 intra-module refs" rule explicitly
   refuses to flag decls that reference each other inside a module,
   because privatizing one without the others would break the build.
   PR 38702 sidesteps this by moving the whole cluster into a
   private-imported sub-module — an action that closes the cluster's
   visibility wholesale. The pipeline as designed does not perform
   this cluster-aware move; it surfaces only the hub (`Real.mk`) and
   leaves the cluster transformation to the human reviewer.

2. **The "30/30" claim in the early write-up referred to census
   presence, not tier membership.** All 39 reachable decls are in
   `data/census_lean.jsonl.gz` with the expected reference counts.
   The meta-program sees what PR 38702 sees; the tiering rules just
   filter more aggressively.

3. **A cluster-aware tiering pass would recover the missing decls.**
   Such a pass would, given a Tier-3 hub, recursively collect its
   in-signature dependents (and their dependents, up to a cap),
   treating the whole closure as a single privatization unit even
   when individual members have intra-module references to other
   closure members. This is not implemented; the current tiering
   evaluates each decl independently.

## Reproducing this trace

```bash
SKIP_CENSUS=1 bash pipeline/scripts/snapshot.sh
# Then in Python against data/census_lean.jsonl.gz:
python3 -c '
import gzip, json
with gzip.open("data/census_lean.jsonl.gz","rt") as f:
    for line in f:
        r = json.loads(line)
        if r["fq_name"].startswith("Real.") and r["defining_module"] == "Mathlib.Data.Real.Basic":
            print(r["fq_name"], r["kind"], r["n_external_users"], r["n_intra_module_refs"])
'
```
