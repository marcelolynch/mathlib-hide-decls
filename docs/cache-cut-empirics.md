# Cache-cut empirics

A controlled experiment on `Mathlib.Data.TwoPointing` verifies that
`private`-body edits leave downstream `.olean.hash` values
byte-identical, so downstream rebuilds cache-hit.

## Setup

`Mathlib.Data.TwoPointing` is a 147-line module with eight
trivially-private candidates (decls with zero external users and zero
intra-module references) and one downstream consumer,
`Mathlib.CategoryTheory.Category.TwoP`.

Pick one candidate, `swap_fst`. Apply a four-state hash matrix: each
state is one single-file edit followed by
`lake build Mathlib.Data.TwoPointing`. Record the resulting hashes:

| state | `swap_fst` | proof body | `olean.hash` | `olean.private.hash` |
|---|---|---|---|---|
| baseline | public | `rfl` | `4ddb6bf124c39a28` | `ef2a1609bd74e827` |
| A | public | `by exact rfl` | `365aee2d7d268987` | `df8aac7faecf2a52` |
| B | private | `rfl` | `87b7873a4c6011a4` | `8800e69d92a3cd56` |
| C | private | `by exact rfl` | **`87b7873a4c6011a4`** | `9be9e1f7d56de549` |
| D | private | `Eq.refl _` | **`87b7873a4c6011a4`** | `349595e641487a30` |

Reading the table:

- **baseline → A** (public, body change): `olean.hash` moves. Downstream cascade triggered.
- **B → C** and **C → D** (private, body change): `olean.hash` byte-identical. Downstream cache-hit. `olean.private.hash` does change.
- **baseline → B** (visibility flip, body unchanged): `olean.hash` moves once because the public surface lost a theorem. One-time cost; subsequent body edits are free.

## Downstream verification

With `swap_fst` private (state C), build the lone downstream
consumer:

```
TwoP.olean.hash before:  d7470cf2fa65bc67
[edit private body of swap_fst]
lake build Mathlib.CategoryTheory.Category.TwoP
TwoP.olean.hash after:   d7470cf2fa65bc67   ← unchanged
```

`Mathlib.CategoryTheory.Category.TwoP` is up-to-date; lake has no
work to do.

## What this measures

- Each `private` flip is a one-time cost. The first build after the
  flip invalidates downstream once. Subsequent body edits to the
  now-private decl are free.
- The benefit compounds with edit frequency. If a private decl's
  body is edited N times, the cache-cut saves N − 1 downstream
  rebuild waves.
- The relevant metric for prioritization is therefore "edits per
  decl per unit time" multiplied by the cost of one downstream
  cascade. `pipeline/src/estimate_impact.py` operationalises this
  against a 1,500-commit master window.

## Reproducing

```bash
MATHLIB_DIR=~/mathlib4 bash pipeline/scripts/cache_demo.sh
```

The script runs the full matrix against a fresh
`Mathlib.Data.TwoPointing` worktree and verifies the unchanged-hash
property on the downstream module.
