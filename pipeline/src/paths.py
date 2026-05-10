"""Path resolution for the pipeline.

The pipeline references three roots:

  * `REPO`     — this repository (`mathlib-hide-decls`).
  * `MATHLIB`  — a working mathlib4 checkout. Configurable via the
                 `MATHLIB_DIR` environment variable; defaults to
                 `$HOME/mathlib4`.
  * `DATA`     — the per-run data directory, `<REPO>/data`.

All scripts import their paths from here so the layout is changed in
one place.
"""

from __future__ import annotations

import gzip
import io
import os
from pathlib import Path

# This file lives at <REPO>/pipeline/src/paths.py — three parents up is REPO.
REPO = Path(__file__).resolve().parents[2]
PIPELINE = REPO / "pipeline"
DATA = REPO / "data"
WORK = DATA / "work"  # transient artefacts from apply / iterate-revert runs

MATHLIB = Path(os.environ.get("MATHLIB_DIR", str(Path.home() / "mathlib4")))

# Canonical input data files. Both `.gz` and uncompressed forms are
# accepted by `open_jsonl`; the .gz form is what we ship.
CENSUS = DATA / "census_lean.jsonl.gz"
CENSUS_UNCOMPRESSED = DATA / "census_lean.jsonl"
RANKED = DATA / "ranked_candidates.jsonl.gz"
RANKED_UNCOMPRESSED = DATA / "ranked_candidates.jsonl"
CHURN_BLAST = DATA / "churn_blast.json"
ESTIMATED_IMPACT = DATA / "estimated_impact.json"

# Per-run working files (transient).
MANIFEST = WORK / "manifest.jsonl"
SKIPPED = WORK / "skipped.jsonl"
REVERTS = WORK / "reverts.jsonl"


def open_jsonl(path: Path):
    """Open a JSONL file for reading. Transparently handles `.gz`.

    If `path` does not exist but its `.gz` sibling does (or vice versa),
    the sibling is opened. This lets callers refer to a single canonical
    location regardless of which form is on disk.
    """
    if path.exists():
        if path.suffix == ".gz":
            return io.TextIOWrapper(gzip.open(path, "rb"), encoding="utf-8")
        return path.open("r", encoding="utf-8")
    sibling = path.with_suffix("") if path.suffix == ".gz" else Path(str(path) + ".gz")
    if sibling.exists():
        if sibling.suffix == ".gz":
            return io.TextIOWrapper(gzip.open(sibling, "rb"), encoding="utf-8")
        return sibling.open("r", encoding="utf-8")
    raise FileNotFoundError(f"neither {path} nor {sibling} exists")


def ensure_work_dir() -> None:
    """Create `data/work/` if it does not already exist."""
    WORK.mkdir(parents=True, exist_ok=True)
