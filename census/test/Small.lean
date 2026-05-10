import Lean
import DeclCensus

/-! Small fixture for the census.

Loads `Mathlib.Logic.Basic` plus its transitive dependencies and runs the
full census on the resulting environment. Useful for verifying the
output schema after a code change without paying the full ~30-minute
census cost.

`Mathlib.Logic.Basic` does not use `@[simps]`, so the `meta_consumers`
and `simps_parent` fields will be empty for every row. For a fixture
that populates them, see `test/Simps.lean`.

Run via:
  cd census
  lake build census_small
  lake env .lake/build/bin/census_small > /tmp/out.jsonl
-/

open Lean

unsafe def main : IO Unit := do
  initSearchPath (← findSysroot)
  Lean.enableInitializersExecution
  IO.eprintln "[census/small] importing Mathlib.Logic.Basic..."
  withImportModules #[{ module := `Mathlib.Logic.Basic }] {} (trustLevel := 1024) fun env => do
    IO.eprintln s!"[census/small] loaded ({env.header.moduleNames.size} modules)"
    DeclCensus.run env
