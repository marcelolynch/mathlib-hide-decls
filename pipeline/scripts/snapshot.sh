#!/usr/bin/env bash
# snapshot.sh — refresh the tracking artefacts.
#
# Runs in order:
#   1. (optional) Lean census  → data/census_lean.jsonl.gz
#   2. rerank.py              → data/ranked_candidates.jsonl.gz
#   3. estimate_impact.py     → data/estimated_impact.json
#                                + data/snapshots/impact_YYYY-MM-DD.json
#   4. build_dashboard.py     → site/index.html + data/dashboard_state.json
#
# Skip the census (~30-45 min) with SKIP_CENSUS=1 to refresh the
# downstream artefacts against an existing census.
#
# Environment:
#   MATHLIB_DIR  defaults to $HOME/mathlib4 (used by the census + impact)
#   PYTHON       defaults to `python3`
#   SKIP_CENSUS  if set to 1, reuse data/census_lean.jsonl.gz
#   SKIP_IMPACT  if set to 1, skip estimate_impact.py (which needs a
#                mathlib worktree with git history)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SRC="$REPO_ROOT/pipeline/src"
DATA="$REPO_ROOT/data"
SNAPSHOTS="$DATA/snapshots"

MATHLIB="${MATHLIB_DIR:-$HOME/mathlib4}"
PYTHON="${PYTHON:-python3}"
DATE="$(date +%Y-%m-%d)"

mkdir -p "$SNAPSHOTS"
export PYTHONPATH="$SRC${PYTHONPATH:+:$PYTHONPATH}"

echo "============================================================"
echo " mathlib-hide-decls snapshot — $DATE"
echo " mathlib:  $MATHLIB"
echo " repo:     $REPO_ROOT"
echo "============================================================"

# Step 1. Census (optional).
if [ "${SKIP_CENSUS:-0}" != "1" ]; then
  CENSUS_DIR="$REPO_ROOT/census"
  if [ ! -d "$CENSUS_DIR/.lake/build" ]; then
    echo ""
    echo "--- building census (first run, will take ~10 min) ---"
    (cd "$CENSUS_DIR" && lake build)
  fi
  echo ""
  echo "--- running census (~30-45 min) ---"
  CENSUS_BIN="$CENSUS_DIR/.lake/build/bin/census"
  CENSUS_OUT="$SNAPSHOTS/census_$DATE.jsonl.gz"
  (cd "$CENSUS_DIR" && lake env "$CENSUS_BIN") | gzip > "$CENSUS_OUT"
  cp "$CENSUS_OUT" "$DATA/census_lean.jsonl.gz"
  echo "  wrote $CENSUS_OUT ($(du -h "$CENSUS_OUT" | cut -f1))"
else
  echo ""
  echo "--- census skipped (SKIP_CENSUS=1) ---"
fi

# Step 2. Rerank.
echo ""
echo "--- rerank ---"
"$PYTHON" "$SRC/rerank.py"
# Compress the ranked output for storage; the .jsonl form is the working file.
if [ -f "$DATA/ranked_candidates.jsonl" ]; then
  gzip -f "$DATA/ranked_candidates.jsonl"
  echo "  → $DATA/ranked_candidates.jsonl.gz"
fi

# Step 3. Impact estimate (optional: needs a mathlib worktree).
if [ "${SKIP_IMPACT:-0}" != "1" ] && [ -d "$MATHLIB/.git" ]; then
  echo ""
  echo "--- impact estimate ---"
  "$PYTHON" "$SRC/estimate_impact.py"
  if [ -f "$DATA/estimated_impact.json" ]; then
    cp "$DATA/estimated_impact.json" "$SNAPSHOTS/impact_$DATE.json"
    echo "  → $SNAPSHOTS/impact_$DATE.json"
  fi
else
  echo ""
  echo "--- impact estimate skipped ---"
fi

# Step 4. Dashboard.
echo ""
echo "--- dashboard ---"
"$PYTHON" "$SRC/build_dashboard.py"
echo "  → $REPO_ROOT/site/index.html"

# Summary.
echo ""
echo "============================================================"
echo " done."
echo "    open file://$REPO_ROOT/site/index.html"
echo "============================================================"
