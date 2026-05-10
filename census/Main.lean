import Lean
import DeclCensus

open Lean

/-- Full-mathlib census entry point.

Loads `Mathlib`, walks every declaration, emits one JSONL row per decl
to stdout. Diagnostic output goes to stderr.

Run via `lake exe census > out/census.jsonl`. Single-threaded, CPU-bound;
typical runtime ~30 minutes on an M-class Mac, longer on GitHub-hosted
runners. -/
unsafe def main : IO Unit := do
  initSearchPath (← findSysroot)
  Lean.enableInitializersExecution
  IO.eprintln "[census] importing Mathlib..."
  withImportModules #[{ module := `Mathlib }] {} (trustLevel := 1024) fun env => do
    IO.eprintln s!"[census] mathlib loaded ({env.header.moduleNames.size} modules)"
    DeclCensus.run env
