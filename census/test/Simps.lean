import Lean
import DeclCensus

/-! `@[simps]`-using fixture for the census.

Loads `Mathlib.Logic.Equiv.Defs`, which uses `@[simps]` heavily, and
runs the full census. Expected output:

  - ~24 rows with `meta_consumers: ["simps"]`
  - ≥ 1 row with `simps_parent` set (e.g. `Equiv.Simps.symm_apply` →
    `simps_parent: "Equiv"`)

Use this to verify the extension-aware fields populate correctly after
a code change to `DeclCensus.lean`'s registry walkers.

Run via:
  cd census
  lake build census_simps
  lake env .lake/build/bin/census_simps > /tmp/out.jsonl
-/

open Lean

unsafe def main : IO Unit := do
  initSearchPath (← findSysroot)
  Lean.enableInitializersExecution
  IO.eprintln "[census/simps] importing Mathlib.Logic.Equiv.Defs..."
  withImportModules
    #[{ module := `Mathlib.Logic.Equiv.Defs }] {} (trustLevel := 1024) fun env => do
    IO.eprintln s!"[census/simps] loaded ({env.header.moduleNames.size} modules)"
    DeclCensus.run env
