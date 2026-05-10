# `census/` — declaration census meta-program

A Lean 4 meta-program that walks every declaration in mathlib's elaborator
state and emits one JSONL row per declaration. The Python pipeline in
`../pipeline/` consumes that JSONL.

## What it captures

Per declaration: fully-qualified name, defining module, kind
(`def` / `theorem` / `lemma` / `abbrev` / …), attributes, name pattern,
has-docstring bit, reference counts from a `Expr.foldConsts` walk over
`info.type` and `info.value?`, plus two extension-aware fields:

- `meta_consumers : Array String` — extension registries that contain
  the decl by name. Currently populated by `simpsAttr`. Other registries
  (`simpExtension`, `normCastExt`, …) are stubbed: their state requires
  a `MetaM` context that this `IO`-rooted census does not enter.
- `simps_parent : Option String` — for decls under a `Foo.Simps.*`
  namespace, the parent struct's fully-qualified name.

Schema details: see `DeclCensus.lean`. The fields consumed downstream
are documented in `../docs/methodology.md §1`.

## Building

```bash
cd census
lake update                 # fetch mathlib at the pinned commit
lake build                  # build all three executables (~10–15 min cold)
```

The pinned mathlib version lives in `lakefile.lean` (`require mathlib
from git ... @ "<rev>"`). Update by editing that line and running
`lake update`.

## Running

Three executables are produced under `.lake/build/bin/`:

| executable | scope | runtime | use |
|---|---|---|---|
| `census` | full Mathlib | ~30–45 min | production data; `> data/census.jsonl` |
| `census_small` | `Mathlib.Logic.Basic` only | ~1 min | spot-check the JSON schema after a code change |
| `census_simps` | `Mathlib.Logic.Equiv.Defs` (uses `@[simps]`) | ~2 min | verify `meta_consumers` + `simps_parent` populate |

Stream JSONL to stdout:

```bash
lake env .lake/build/bin/census > /tmp/census.jsonl
```

The pipeline expects the output gzipped at `../data/census_lean.jsonl.gz`:

```bash
lake env .lake/build/bin/census | gzip > ../data/census_lean.jsonl.gz
```

## Schema

Each row is a single-line JSON object. Field names match the
`ForwardRec` structure in `DeclCensus.lean`. `null` is emitted as
JSON `null`; arrays are JSON arrays; missing values for optional
fields are emitted as `null`.

```jsonc
{
  "fq_name": "Equiv.arrowCongr",
  "defining_module": "Mathlib.Logic.Equiv.Defs",
  "kind": "def",
  "namespace": "Equiv",
  "leaf": "arrowCongr",
  "is_private": false,
  "has_docstring": true,
  "name_pattern": "normal",
  "forbidden_attrs": [],
  "n_external_users": 7,
  "n_external_users_sig": 4,
  "n_external_users_body": 3,
  "n_intra_module_refs": 12,
  "signature_referenced_by_intra": ["Equiv.arrowCongr_apply", ...],
  "n_signature_refs": 4,
  "n_sig_refs_fwd": 1,
  "n_body_refs_fwd": 0,
  "meta_consumers": ["simps"],
  "simps_parent": null
}
```

## Architecture

`DeclCensus.lean` is structured as three passes over the `Environment`:

1. **Forward pass** (`gatherForward`): for every declaration, build a
   `ForwardRec` capturing the per-decl shape, attributes, and the lists
   of `Expr.foldConsts` references in its type and body.
2. **Reverse pass** (`buildReverseMaps`): invert the forward references
   into "who references X". Two reverse maps are built: one for
   signature references, one for body references.
3. **Emit pass** (`emit`): for each ForwardRec, compute the derived
   fields (`n_external_users`, `n_intra_module_refs`,
   `signature_referenced_by_intra`, …) by joining against the reverse
   maps, then serialise to JSONL.

The forward pass is the bottleneck (CPU-bound on `foldConsts`). Output
is buffered for streaming so the consumer can `tail`-style consume.
