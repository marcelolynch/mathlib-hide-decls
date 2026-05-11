# PR 38702 trace

Mathlib4 PR
[#38702](https://github.com/leanprover-community/mathlib4/pull/38702)
(`chore(Data/Real): encapsulate real numbers`) is cited in the
dashboard as the canonical worked example of sub-module
encapsulation. The PR is currently open; this trace records, against
the latest census and the current policy, which of its 40 privatized
decls the pipeline surfaces and why the rest do not.

## Summary

| outcome | count |
|---|---:|
| Surfaced as **Tier 3** hub | 2 (`Real.mk`, `Real.equivCauchy`) |
| Reachable as **co-located** under a surfaced hub | 22 |
| Blocked at hub level: **`@[reducible]`** | 13 (anchored to `Real.cauchy`) |
| Not in any cluster (bridging lemmas referenced only via proof bodies) | 2 (`Real.isCauSeq_iff_lift`, `Real.of_near`) |
| Absent from census | 1 (`Real.sub_def`, elaborated away) |

**Reachable through the dashboard: 24 of 40.** All 16 remaining decls
trace back to one of three causes: their hub is blocked by the
`@[reducible]` policy (13), they're bridging lemmas with no
structural hub (2), or the kernel collapses them before the
meta-program sees them (1).

## The hub model

The pipeline organises Tier 3 around **hubs**: a `def`, `abbrev`, or
`ctor` whose type signature is referenced by at least 2 same-module
decls. Each hub's row expands to a *Co-located decls* column listing
every same-module decl that references the hub in its type. The
intended action is to move the hub and every co-located decl into a
sub-namespace that the parent imports privately.

PR 38702 follows this pattern. Four hubs anchor its 40 privatizations:

| hub | kind | `n_sig_refs` | dashboard status | Tier-3 rank (of 25,418) | PR theorems in co-located list |
|---|---|---:|---|---:|---:|
| `Real.mk` | `def` | 26 | **Tier 3** | 445 | 11 |
| `Real.ofCauchy` | `ctor` | 52 | **Tier 3** | **83** | 11 |
| `Real.equivCauchy` | `def` | 2 | **Tier 3** (hub itself) | 16,999 | 0 |
| `Real.cauchy` | `def` | 17 | blocked: `@[reducible]` in `forbidden_attrs` | — | 13 (unreachable) |

Three of the four hubs surface. The fourth (`Real.cauchy`) is
hub-shaped but carries the `@[reducible]` attribute, which
`policy.toml` rejects because privatizing a `@[reducible]` decl
removes its body from the unfolding path for cross-module callers,
defeating the attribute's purpose.

`Real.ofCauchy` and `Real.mk`, the two meaty hubs (n_sig=52 and 26),
land inside the dashboard's top-1000 cut. `Real.equivCauchy` is
hub-shaped (n_sig=2) but its cluster is too thin to compete with
larger-n_sig hubs at comparable bcp under the current Tier-3 scoring;
it surfaces as a reachable hub but not on the default top-1000 view.

## Per-decl trace

| decl | kind | `n_ext` | `n_sig` | hub | hub status | dashboard reach |
|---|---|---:|---:|---|---|---|
| `Real.mk` | def | 1 | 26 | (self) | — | **Tier 3** |
| `Real.equivCauchy` | def | 1 | 2 | (self) | — | **Tier 3** |
| `Real.ofCauchy` (implicit) | ctor | — | 52 | (self) | — | **Tier 3** |
| `Real.sub_def` | — | — | — | — | — | absent from census |
| `Real.mk_add` | theorem | 0 | 0 | `Real.mk` | — | reachable |
| `Real.mk_const` | theorem | 0 | 0 | `Real.mk` | — | reachable |
| `Real.mk_eq` | theorem | 0 | 0 | `Real.mk` | — | reachable |
| `Real.mk_le` | theorem | 0 | 0 | `Real.mk` | — | reachable |
| `Real.mk_lt` | theorem | 0 | 0 | `Real.mk` | — | reachable |
| `Real.mk_mul` | theorem | 0 | 0 | `Real.mk` | — | reachable |
| `Real.mk_neg` | theorem | 0 | 0 | `Real.mk` | — | reachable |
| `Real.mk_one` | theorem | 0 | 0 | `Real.mk` | — | reachable |
| `Real.mk_pos` | theorem | 0 | 0 | `Real.mk` | — | reachable |
| `Real.mk_zero` | theorem | 0 | 0 | `Real.mk` | — | reachable |
| `Real.ind_mk` | theorem | 1 | 0 | `Real.mk` | — | reachable |
| `Real.ofCauchy_add` | theorem | 0 | 0 | `Real.ofCauchy` | — | reachable |
| `Real.ofCauchy_intCast` | theorem | 0 | 0 | `Real.ofCauchy` | — | reachable |
| `Real.ofCauchy_inv` | theorem | 0 | 0 | `Real.ofCauchy` | — | reachable |
| `Real.ofCauchy_mul` | theorem | 0 | 0 | `Real.ofCauchy` | — | reachable |
| `Real.ofCauchy_natCast` | theorem | 0 | 0 | `Real.ofCauchy` | — | reachable |
| `Real.ofCauchy_neg` | theorem | 0 | 0 | `Real.ofCauchy` | — | reachable |
| `Real.ofCauchy_nnratCast` | theorem | 0 | 0 | `Real.ofCauchy` | — | reachable |
| `Real.ofCauchy_one` | theorem | 0 | 0 | `Real.ofCauchy` | — | reachable |
| `Real.ofCauchy_ratCast` | theorem | 0 | 0 | `Real.ofCauchy` | — | reachable |
| `Real.ofCauchy_sub` | theorem | 0 | 0 | `Real.ofCauchy` | — | reachable |
| `Real.ofCauchy_zero` | theorem | 0 | 0 | `Real.ofCauchy` | — | reachable |
| `Real.cauchy_add` | theorem | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_inv` | theorem | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_intCast` | theorem | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_mul` | theorem | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_natCast` | theorem | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_neg` | theorem | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_nnratCast` | theorem | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_one` | theorem | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_ratCast` | theorem | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_sub` | theorem | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.cauchy_zero` | theorem | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.ext_cauchy` | theorem | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.ext_cauchy_iff` | theorem | 0 | 0 | `Real.cauchy` | `@[reducible]` | unreachable |
| `Real.isCauSeq_iff_lift` | theorem | 0 | 0 | — | (no hub) | not in any cluster |
| `Real.of_near` | theorem | 0 | 0 | — | (no hub) | not in any cluster |

`n_sig = 0` for every PR theorem because theorem references happen in
proof bodies, not in type signatures. Theorems are structurally
admissible by the Tier-1 gate (`n_external_users == 0`,
`n_signature_refs == 0`); the theorem-intent gate would block them
individually (`name_pattern=normal`, no docstring) but they remain
reachable as co-located dependents of their hub.

## History of this trace

The pipeline's coverage of PR 38702 has improved across three
ranker changes:

| ranking | hubs surfaced | coverage |
|---|:-:|---:|
| initial (May 2026) | `Real.mk` only | 12 / 40 |
| Tier-1 rule loosened to `n_signature_refs == 0` | `Real.mk` only | 12 / 40 (Tier-1 gate wasn't binding for these decls) |
| Tier-3 admits `ctor` + threshold `n_sig_refs ≥ 2` | `Real.mk`, `Real.equivCauchy`, `Real.ofCauchy` | **24 / 40** |
| Tier-3 score uses `log1p(bcp)` instead of the saturation form | same three hubs; `Real.ofCauchy` lifts from below the top-1000 cut to rank 83 | **24 / 40** (coverage unchanged; visibility improved for the meaty hubs) |

The remaining 16 break down: 13 unreachable because their hub
(`Real.cauchy`) carries `@[reducible]`; 2 are bridging lemmas with no
structural hub; 1 (`Real.sub_def`) is elaborated away before the
meta-program runs.

## What remains

| refinement | recovers | risk |
|---|---:|---|
| Surface `@[reducible]` hubs with a warning annotation rather than dropping them | 13 (would lift to 37 / 40) | medium: reducibility implications are real but invisible to the build-verification loop (they manifest in downstream user code, not mathlib's own build) |
| Relax the theorem-intent gate for theorems co-located under a surfaced hub | 0 net for PR 38702 (those theorems are already reachable through their hubs) but unblocks individual privatization for many other clusters elsewhere | low (the encapsulation move provides the safety the intent gate was hedging against) |
| None for `Real.isCauSeq_iff_lift` and `Real.of_near` | 2 | — (these are bridging lemmas referenced only via proof bodies and don't fit any structural hub) |
| None for `Real.sub_def` | 1 | — (kernel-elaborated; would require a different meta-program approach to detect) |

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
            print(r["fq_name"], r["kind"], r["n_external_users"],
                  r["n_intra_module_refs"], r.get("n_signature_refs"))
'
```
