# PR 38702 trace

Mathlib4 PR
[#38702](https://github.com/leanprover-community/mathlib4/pull/38702)
(`chore(Data/Real): encapsulate real numbers`) is cited in the
dashboard as the canonical worked example of sub-module
encapsulation. The PR is currently open; this trace records, against
the latest census, which of its 40 privatized decls the pipeline
surfaces and why the rest do not.

The short answer: of the 40, **12 are reachable through the dashboard
today**, and **24 more are present in the underlying data but unreachable
because their Tier-3 hub is filtered out by a policy gate**. Only 3 PR
decls fall outside the model entirely, plus 1 that the meta-program
does not see at all.

## The hub model

The pipeline organises Tier 3 around **hubs**: a `def` whose
type signature is referenced by at least 5 same-module decls. The
hub's row in the dashboard expands to a *Co-located decls* column
listing every same-module decl that references the hub in its type.
The intended action for a Tier-3 row is to move the hub and every
co-located decl into a sub-namespace that the parent imports
privately.

PR 38702 follows exactly this pattern. Four hubs anchor the
declarations the PR privatizes:

| hub | kind | `n_sig_refs` | how the pipeline treats it | dependents in the co-located list |
|---|---|---:|---|---:|
| `Real.mk` | `def` | 26 | **Tier 3** | 11 PR theorems |
| `Real.cauchy` | `def` | 17 | blocked: `@[reducible]` is in `forbidden_attrs` | 13 PR theorems (unreachable) |
| `Real.ofCauchy` | `ctor` | 52 | blocked: `kind == ctor`, structure constructor | 11 PR theorems (unreachable) |
| `Real.equivCauchy` | `def` | 2 | blocked: `n_sig_refs < 5` threshold | 0 PR theorems |

`Real.mk` is the only hub that surfaces; the other three are stopped
by different filters. The theorems anchored to those three hubs are
*present in the census* and listed under those hubs' co-located fields
in the underlying data — but because the hub row is not rendered, the
dependents are not reachable through the dashboard.

## Coverage breakdown

| status | count | notes |
|---|---:|---|
| Hub itself, surfaced as Tier 3 | 1 | `Real.mk` |
| Co-located dependent of a surfaced hub | 11 | visible under `Real.mk` in the dashboard |
| Co-located dependent of a hub blocked by policy | 24 | data is present, hub row is not rendered |
| Not associated with any hub (`n_sig_refs == 0` for every PR member that references it) | 3 | `Real.isCauSeq_iff_lift`, `Real.of_near`, `Real.sub_def` |
| Absent from census | 1 | `Real.sub_def` (kernel elaborates it away before the meta-program runs) |
| **Total** | **40** | |

Note: `Real.sub_def` appears in two lines (uncovered + absent); the
40 sums match when each decl is counted once.

The 24 "data present but hub blocked" decls split as follows:

| their hub | hub's block reason | count |
|---|---|---:|
| `Real.cauchy` | `forbidden_attrs = [reducible]`: `policy.toml` refuses `@[reducible]` because privatizing removes the body from cross-module callers, defeating the attribute. PR 38702 chose to absorb this cost. | 13 |
| `Real.ofCauchy` | `kind = ctor`: a structure constructor, not a `def` or `abbrev`. Constructors are auto-generated structure surface, not user-facing building blocks. The PR privatizes theorems *about* the constructor; the constructor itself stays public. | 11 |

## Why this isn't strictly a "30 missing theorems" problem

The earlier framing of "30 theorems blocked by Tier-1's
`n_intra_module_refs > 0` gate" mis-stated the structure. Theorems
were never going to surface as their own Tier-3 candidates, regardless
of how their reference counts shake out, because:

1. **Tier 3 requires `kind ∈ {def, abbrev}`.** Theorems are filtered
   out at the kind check, before any reference-count threshold applies.
2. **Even if the kind filter were relaxed, the theorems would still
   fail.** Empirically, every PR-38702 theorem has
   `n_signature_refs == 0`. References to a theorem `cauchy_add`
   happen in the *proofs* of other lemmas, not in their type
   signatures. The `n_signature_refs ≥ 5` rule measures structural
   building-block-ness, which theorem references almost never produce.

The right place to look for those theorems is under a hub's Co-located
column. The pipeline's mental model and PR 38702's action are aligned:
*move the def hub plus its in-signature dependents*. The pipeline is
correct in surfacing the cluster around `Real.mk`. It just fails to
surface the clusters around `Real.cauchy` and `Real.ofCauchy` because
the policy excludes those hubs for reasons that do not apply to the
cluster's theorems.

## Per-decl trace

| decl | kind | `n_ext` | `n_intra` | `n_sig` | hub | hub block | dashboard reach |
|---|---|---:|---:|---:|---|---|---|
| `Real.mk` | def | 1 | 41 | 26 | (self) | — | **Tier 3** |
| `Real.equivCauchy` | def | 1 | 3 | 2 | (self) | `n_sig_refs < 5` | not surfaced |
| `Real.sub_def` | — | — | — | — | — | — | absent from census |
| `Real.cauchy_add` | theorem | 0 | 10 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_inv` | theorem | 0 | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_intCast` | theorem | 0 | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_mul` | theorem | 0 | 9 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_natCast` | theorem | 0 | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_neg` | theorem | 0 | 3 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_nnratCast` | theorem | 0 | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_one` | theorem | 0 | 3 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_ratCast` | theorem | 0 | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_sub` | theorem | 0 | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_zero` | theorem | 0 | 6 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.ext_cauchy` | theorem | 0 | 16 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.ext_cauchy_iff` | theorem | 0 | 2 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.ind_mk` | theorem | 1 | 15 | 0 | `Real.mk` | — | reachable (under `Real.mk`) |
| `Real.isCauSeq_iff_lift` | theorem | 0 | 1 | 0 | — | (no hub) | not in any cluster |
| `Real.mk_add` | theorem | 0 | 1 | 0 | `Real.mk` | — | reachable |
| `Real.mk_const` | theorem | 0 | 2 | 0 | `Real.mk` | — | reachable |
| `Real.mk_eq` | theorem | 0 | 2 | 0 | `Real.mk` | — | reachable |
| `Real.mk_le` | theorem | 0 | 6 | 0 | `Real.mk` | — | reachable |
| `Real.mk_lt` | theorem | 0 | 4 | 0 | `Real.mk` | — | reachable |
| `Real.mk_mul` | theorem | 0 | 1 | 0 | `Real.mk` | — | reachable |
| `Real.mk_neg` | theorem | 0 | 1 | 0 | `Real.mk` | — | reachable |
| `Real.mk_one` | theorem | 0 | 0 | 0 | `Real.mk` | — | reachable |
| `Real.mk_pos` | theorem | 0 | 1 | 0 | `Real.mk` | — | reachable |
| `Real.mk_zero` | theorem | 0 | 1 | 0 | `Real.mk` | — | reachable |
| `Real.ofCauchy_add` | theorem | 0 | 2 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_intCast` | theorem | 0 | 1 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_inv` | theorem | 0 | 2 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_mul` | theorem | 0 | 3 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_natCast` | theorem | 0 | 2 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_neg` | theorem | 0 | 2 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_nnratCast` | theorem | 0 | 1 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_one` | theorem | 0 | 3 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_ratCast` | theorem | 0 | 2 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_sub` | theorem | 0 | 0 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_zero` | theorem | 0 | 3 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.of_near` | theorem | 0 | 0 | 0 | — | (no hub) | not in any cluster |

## Implications for the pipeline

The trace identifies two concrete, actionable gaps.

1. **Relax `kind=ctor` for Tier-3 hub eligibility, when the constructor
   is the canonical access point to a structure.** `Real.ofCauchy`
   acts structurally as a hub: 52 same-module decls reference it in
   their type. Treating it as a Tier-3 candidate would surface 11
   PR-38702 theorems with no further policy changes.

2. **Make the `@[reducible]` block configurable, or add a "list as
   hub but warn" mode.** `Real.cauchy` is a perfectly hub-shaped def
   that is currently dropped entirely. The PR's author chose to
   privatize it despite the reducibility implications. The pipeline
   could surface it with the cost annotation rather than hide it.

3. **Move the `n_signature_refs < 5` threshold to a soft signal.**
   `Real.equivCauchy` falls just below the threshold and would be a
   reasonable Tier-3 hub for the PR's author. The threshold is a
   heuristic for "this cluster is worth a sub-module split," not a
   correctness rule.

Each of these would improve PR-38702 coverage from 12 to 35+ without
changing the model. The remaining 3 PR theorems (`Real.of_near`,
`Real.isCauSeq_iff_lift`, `Real.sub_def`) genuinely don't fit the
hub model — `of_near` and `isCauSeq_iff_lift` are bridging lemmas
referenced via proof bodies only; `sub_def` is invisible to the
meta-program.

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
