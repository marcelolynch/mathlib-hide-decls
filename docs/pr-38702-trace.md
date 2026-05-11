# PR 38702 trace

Mathlib4 PR
[#38702](https://github.com/leanprover-community/mathlib4/pull/38702)
(`chore(Data/Real): encapsulate real numbers`) is cited in the
dashboard as the canonical worked example of sub-module
encapsulation. The PR is currently open; this trace records, against
the latest census, which of its 40 privatized decls the pipeline
surfaces and why the rest do not.

## Summary

| outcome | count | reason |
|---|---:|---|
| Surfaced as **Tier 3** (hub itself) | 1 | `Real.mk` |
| Reachable as **co-located** under `Real.mk` | 11 | rendered in the hub's expandable Co-located column |
| Soft-blocked by **theorem-intent gate** | 24 | theorem with `name_pattern=normal` and no docstring → treated as public API |
| Blocked at hub level: **`@[reducible]`** | (13 dependents) | their hub `Real.cauchy` carries `@[reducible]` which `policy.toml` rejects |
| Blocked at hub level: **`kind=ctor`** | (11 dependents) | their hub `Real.ofCauchy` is a structure constructor, not a `def` |
| Blocked: **n_sig_refs < 5 threshold** | 1 def + 0 dependents | `Real.equivCauchy` (`n_sig_refs=2`) |
| Absent from census | 1 | `Real.sub_def` (elaborated away before the meta-program runs) |

**Reachable through the dashboard today: 12 of 40.** The other 27
fall into one of two categories: blocked at the *intent gate* (theorems
the policy considers ambiguous), or blocked at the *hub level* (the
hub they depend on is filtered out for an unrelated reason).

## The hub model

The pipeline organises Tier 3 around **hubs**: a `def` whose type
signature is referenced by at least 5 same-module decls. The hub's row
expands to a *Co-located decls* column listing every same-module decl
that references the hub in its type. The intended action for a Tier-3
row is to move the hub and every co-located decl into a sub-namespace
that the parent imports privately.

PR 38702 follows this pattern. Four hubs anchor its 40 privatizations:

| hub | kind | `n_sig_refs` | how the pipeline treats it | PR theorems in its co-located list |
|---|---|---:|---|---:|
| `Real.mk` | `def` | 26 | **Tier 3** | 11 |
| `Real.cauchy` | `def` | 17 | blocked: `@[reducible]` in `forbidden_attrs` | 13 (unreachable) |
| `Real.ofCauchy` | `ctor` | 52 | blocked: `kind == ctor` (structure constructor) | 11 (unreachable) |
| `Real.equivCauchy` | `def` | 2 | blocked: `n_sig_refs < 5` threshold | 0 |

`Real.mk` is the only hub that surfaces. The 13 + 11 PR theorems
anchored to `Real.cauchy` and `Real.ofCauchy` are *present in the
census* and listed under those hubs' co-located fields in the
underlying data, but because the hub row is not rendered, the
dependents are not reachable through the dashboard.

## Why theorems aren't candidates in their own right

In addition to the hub-level filters, the PR's theorems hit a
*per-decl* gate: the theorem-intent gate.

Tier 1 admits theorems only when they carry an "intended-internal"
signal: a `name_pattern ∈ {underscore_prefix, aux, internal_namespace}`
or a docstring marker explicitly tagging them as internal. The PR
theorems have `name_pattern=normal` and no docstring, so the intent
gate rejects them as plausibly public API. This is intentional: the
pipeline prefers false negatives over false positives for theorems,
because mis-privatizing a theorem users depend on is a more expensive
mistake than failing to suggest a privatization.

The structural gate (`n_external_users == 0`, `n_signature_refs == 0`)
already admits the PR theorems — they are structurally safe to
privatize. The block is purely about *intent*, not safety.

## Per-decl trace

| decl | kind | `n_ext` | `n_sig` | hub | hub status | dashboard reach |
|---|---|---:|---:|---|---|---|
| `Real.mk` | def | 1 | 26 | (self) | — | **Tier 3** |
| `Real.equivCauchy` | def | 1 | 2 | (self) | `n_sig < 5` | not surfaced |
| `Real.sub_def` | — | — | — | — | — | absent from census |
| `Real.mk_add` | theorem | 0 | 0 | `Real.mk` | — | reachable (under `Real.mk`) |
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
| `Real.ofCauchy_add` | theorem | 0 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_intCast` | theorem | 0 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_inv` | theorem | 0 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_mul` | theorem | 0 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_natCast` | theorem | 0 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_neg` | theorem | 0 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_nnratCast` | theorem | 0 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_one` | theorem | 0 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_ratCast` | theorem | 0 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_sub` | theorem | 0 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.ofCauchy_zero` | theorem | 0 | 0 | `Real.ofCauchy` | `kind=ctor` | unreachable |
| `Real.isCauSeq_iff_lift` | theorem | 0 | 0 | — | (no hub) | not in any cluster |
| `Real.of_near` | theorem | 0 | 0 | — | (no hub) | not in any cluster |

Note: `n_sig` here is the count of same-module decls that reference
the row's decl in their type signature. All PR theorems have
`n_sig = 0` because theorem references happen in proof bodies, not in
type signatures. They are structurally admissible; what excludes them
is either the intent gate (when a hub's co-located column would
cover them) or the hub-level filter.

## Implications for the pipeline

The trace identifies four concrete refinements, ordered by impact on
PR-38702 coverage:

1. **Relax `kind=ctor` for hub eligibility** (recovers 11 dependents).
   `Real.ofCauchy` acts structurally as a hub: 52 same-module decls
   reference it in their type. The current policy excludes
   constructors entirely, but a structure's primary constructor is
   often the cleanest hub for an encapsulation move.

2. **Make the `@[reducible]` block softer** (recovers 13 dependents).
   `Real.cauchy` is a hub-shaped def currently dropped entirely. The
   PR's author chose to privatize it despite the reducibility
   implications. The pipeline could surface it with a cost annotation
   rather than hide it.

3. **Relax the theorem-intent gate when a theorem is in the
   co-located list of a surfaced hub.** The intent gate is conservative
   because, in isolation, the pipeline can't tell whether a theorem is
   public API. But when the theorem is structurally part of a Tier-3
   hub's cluster, the encapsulation move provides the safety: the
   theorem moves into the sub-namespace alongside the hub, so its
   visibility is closed wholesale. This would recover 11 PR theorems
   already covered by `Real.mk`'s co-located list — currently they show
   up in the Co-located column but the dashboard doesn't acknowledge
   they are themselves admissible privatization targets.

4. **Soften the `n_sig_refs < 5` threshold to a sort key rather than a
   filter** (recovers `Real.equivCauchy`). `equivCauchy` falls just
   below the threshold and would be a reasonable Tier-3 hub. The
   threshold is a heuristic for "this cluster is worth a sub-module
   split," not a correctness rule.

Items 1, 2, and 4 would raise coverage from 12 to 35+. Item 3 is the
hardest one to make safe in general but is the only path to
individually identifying theorems like the `cauchy_*` family as
candidates rather than as dependents.

## Note on the Tier-1 refinement

In May 2026 the Tier-1 mech-hidable rule was loosened from
`n_intra_module_refs == 0` to `n_signature_refs == 0`. Body
references inside the same module no longer constrain Tier-1
admissibility, because private decls remain visible inside their
defining module and proofs that reference them continue to
type-check.

The refinement nearly doubled the Tier-1 candidate pool (4,269 →
8,124) and the Tier-2 bundle count (361 → 718). It did **not** change
PR-38702 coverage: the PR theorems are blocked by the theorem-intent
gate, not the structural gate, and the refinement did not touch
intent. PR-38702 coverage is unchanged at 12/40 before and after the
refinement.

The refinement matters elsewhere — most newly admitted candidates are
internal-pattern theorems and defs with body references — but for the
specific calibration target of PR 38702, the path to better coverage
runs through the four hub-level refinements above, not through
structural-gate relaxation.

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
