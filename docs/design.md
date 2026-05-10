# Design

A prescriptive description of the pipeline. For the rationale of
particular thresholds and the per-tier policy decisions, see
`methodology.md`.

## Goal

Find every declaration in mathlib whose privatization is

1. mechanically applicable as a single `def → private def` edit,
2. semantically safe (the declaration is not consumed by a name-based
   mechanism that requires public visibility),
3. verifiable by `lake build`.

Rank candidates by the rebuild-CP cost of editing their defining
module, so that successful privatizations concentrate where they save
the most rebuild work.

## Cache-cut mechanism

The Lean 4.10 module system places each module into three artifacts:

- `M.olean` — public surface as seen by importers.
- `M.olean.private` — bodies of `private` declarations.
- `M.olean.server` — server-only metadata.

A downstream module's incremental rebuild keys on
`M.olean.hash`. The hash includes the bodies of public declarations
but excludes those of private ones. Editing a private body therefore
leaves `M.olean.hash` byte-identical and downstream rebuilds
cache-hit. `docs/cache-cut-empirics.md` walks an empirical hash table.

This saves rebuild work in proportion to:

1. how often the privatized declaration's body is edited
2. how much downstream work the cascade triggered by editing it
   without privatization would cost

The scoring formula in `methodology.md` operationalises both.

## Pipeline stages

```
  ┌──────────┐    ┌──────────┐    ┌────────────┐    ┌─────────────────┐    ┌──────────┐
  │ Census   │ →  │ Re-rank  │ →  │ Apply      │ →  │ Iterate-revert  │ →  │ Verify   │
  │ (Lean)   │    │ (Python) │    │ (Python)   │    │ (build → parse  │    │ (build)  │
  │          │    │ + policy │    │            │    │  errors → revert)│   │          │
  └──────────┘    └──────────┘    └────────────┘    └─────────────────┘    └──────────┘
   census.jsonl    ranked.jsonl    manifest.jsonl    reverts.jsonl          PASS / FAIL
```

### 1. Census (`census/`)

A Lean 4 meta-program runs inside the elaborator, walks every constant
in every olean, and emits one JSONL row per decl. The output captures
fully-qualified name, defining module, kind, attributes, name pattern,
has-docstring bit, and reference counts from `Expr.foldConsts` over
`info.type` and `info.value?`.

A meta-program is preferred over text scanning for correctness: the
elaborator knows the true fully-qualified name (no namespace
ambiguity), the actual reference set (no false positives from comment
text), and elaborator-internal flags that text cannot recover.

Single-threaded, CPU-bound; ~30–45 minutes for the full mathlib.

### 2. Re-ranking (`pipeline/src/rerank.py`)

Reads the census, applies `policy.toml`'s hard blocks, and bins
declarations into three tiers:

- **Tier 1** — single-decl candidates: `n_external_users == 0`,
  `n_intra_module_refs == 0`, intent-safe, policy-clean. One
  `private` edit per decl.
- **Tier 2** — module bundles: modules with ≥ 3 tier-1 decls,
  grouped by `defining_module`. One PR per module.
- **Tier 3** — sub-module encapsulation candidates: `kind ∈ {def,
  abbrev}`, `n_signature_refs ≥ 5`, `n_external_users ≤ 30`. Action
  is to move the decl and its in-signature dependents into a
  sub-namespace that the parent imports privately.

Each module gets a score from `methodology.md §4`.

### 3. Apply (`pipeline/src/bulk_apply.py` or `iterate_bundle.sh`)

Two front-ends share the same apply primitive:

- **Bulk apply** privatises every tier-1 candidate across mathlib in
  a single pass, producing one WIP commit and a manifest of every
  applied row.
- **Per-bundle apply** privatises the candidates of one module at a
  time, running a lake build of importers up to a 4-importer cap
  before committing. Produces a series of small per-module commits.

The shared apply primitive does the same thing in both cases: for
each matched `def` / `abbrev` / `theorem` / `lemma` line, it prepends
`private ` after any `@[…]` attribute group on the same line and
before any other modifier (`noncomputable`, `partial`, `unsafe`). The
result reads `@[<attrs>] private noncomputable def …`, matching
Lean-conventional keyword order.

The forbidden-attribute scan considers two regions: same-line `@[…]`
groups before the kind keyword, and preceding contiguous lines that
are `@[…]` blocks, doc comments, or blank. Both must be checked: a
same-line-only scanner misses `@[simp]\nlemma X`; a preceding-only
scanner misses `@[simp] lemma X`. The scan stops at the first non-attr
non-comment non-blank line (which signals the previous decl).

The apply step writes `data/work/manifest.jsonl`, one row per
privatization, recording `(fq_name, file, line, kind, module)`. This
manifest is the input to revert.

> **Manifest invariant.** `fq_name` is not unique. The same dotted
> name can be declared under different `namespace … end` brackets
> in one file. Code that consumes the manifest must key by
> `(file, line)` or hold a `dict[fq → list[row]]`, not a flat
> `dict[fq → row]`. The revert tooling does the latter.

### 4. Iterate-revert (`pipeline/src/bulk_revert.py`)

Takes a failing `lake build` log and produces a list of `private `
prefixes to strip. The log parser recognises nine per-decl error
patterns (see the dashboard's Methodology tab for the table) plus a
module-wide trigger for unrecognised cascading errors that name a
file but not a decl.

When a parsed offending name does not directly match a manifest
entry — common with auto-derived names like `X.foo_apply` from
`@[simps]` — the revert step walks a fallback ladder:

1. Exact match in the manifest (loops over all rows for that fq).
2. Suffix match: revert any manifest entry ending in `.X`.
3. Namespace-prefix sweep: revert every manifest entry sharing the
   longest prefix.
4. Grep-define-site: grep mathlib for files defining a leaf with
   the right name, then revert every manifest entry from those files.

For module-wide errors, the revert step undoes every manifest entry
whose `module` matches the failing file's module path.

The driver shell script (`pipeline/scripts/bulk_iterate.sh`) loops:
build → revert → amend WIP commit → build, until either the build
passes or the revert step produces zero reverts.

### 5. Verify

A clean `lake build` from the mathlib root certifies that retained
privatizations are sound. The pipeline holds the mathlib branch in a
single WIP commit so this verification authoritatively covers the
final state.

## Two operating modes

The pipeline supports two modes with different tradeoffs:

### Bulk

Apply every tier-1 candidate across mathlib in one commit. Loop
build → revert → amend → build until convergence. Output: one large
WIP commit with end-to-end build verification.

When to use:
- You want a measurement of how much privatization is feasible right
  now under the current policy.
- You want full-mathlib build verification on the final state.
- You don't need the diff to be reviewable in pieces.

### Per-bundle

Apply per module. Lake-build importers up to a 4-importer cap before
committing. Cap-fail bumps to a "needs review" list rather than
reverting in place. Output: a series of small, independently
reviewable commits.

When to use:
- You want individual PRs maintainers can review and merge
  independently.
- You want each commit to come with its own per-bundle build proof.

The 4-importer cap is a convenience for review ergonomics, not a
correctness requirement. Both pipelines run a final full-mathlib
build to catch dot-method references and `@[simps]`-derived names
beyond any per-bundle horizon.

## Policy

`pipeline/policy.toml` is the single source of truth for what the
apply step will refuse to touch. Three hard-block categories:

- `forbidden_attrs` — attributes whose presence is a semantic risk
  (`reducible`, `implicit_reducible`, `deprecated`, `inline`). A
  `private` annotation does not change semantics, but these decls
  participate in mechanisms (typeclass resolution, reducibility,
  deprecation tooling) where downstream user code may depend on
  visibility.

- `build_rejected_attrs` — attributes whose extension point looks up
  the decl by name at attribute-elaboration time (`simp`, `norm_cast`,
  `ext`, `macro`, `fun_prop`, `positivity`, `norm_num`, `simps`,
  `instance`, `coe`, `gcongr`, `mono`, …). Lean rejects `private`
  on a decl carrying any of these.

- `forbidden_name_patterns` — name patterns that signal the decl is
  consumed by a name-based mechanism without carrying an obvious
  attribute. Currently: `simps_projection` (decls under a
  `Foo.Simps.*` namespace).

- `forbidden_module_prefixes` — module-path prefixes whose decls
  bypass tier-1 (currently `Mathlib.Tactic.`, `Mathlib.Meta.`,
  `Mathlib.Lean.`).

The same policy file is consumed by `rerank.py`, `bulk_apply.py`,
`iterate_bundle.sh`, and `build_dashboard.py`. Editing
`policy.toml` reflows all of them.

## Repository layout

See the layout table in `README.md`.
