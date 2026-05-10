import Lake

open Lake DSL

package «mathlib-hide-decls-census» where
  -- Compile with C optimisation; the census is CPU-bound on Expr.foldConsts.
  leanOptions := #[⟨`debug.skipKernelTC, false⟩]

require mathlib from git
  "https://github.com/leanprover-community/mathlib4.git" @ "master"

lean_lib DeclCensus

/-- Full-mathlib census. Loads `Mathlib`, walks every declaration, emits JSONL. -/
@[default_target]
lean_exe census where
  root := `Main

/-- Small fixture: loads `Mathlib.Logic.Basic` only. Used to verify that the
    census still emits the expected schema after a code change. -/
lean_exe census_small where
  root := `test.Small

/-- @[simps]-using fixture: loads `Mathlib.Logic.Equiv.Defs` so the
    `meta_consumers` and `simps_parent` fields are populated for at least
    one row in the output. -/
lean_exe census_simps where
  root := `test.Simps
