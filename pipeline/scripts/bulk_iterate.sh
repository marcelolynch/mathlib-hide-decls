#!/usr/bin/env bash
# bulk_iterate.sh — drive the apply -> build -> revert loop to convergence.
#
# State assumed:
#   - $MATHLIB_DIR points at a mathlib4 worktree on the experiment branch.
#   - The branch already has bulk_apply.py's WIP commit at HEAD.
#   - $PYTHON points at a Python 3.11+ interpreter with the pipeline
#     dependencies importable (pipeline/src on PYTHONPATH).
#
# Loop: each iteration runs `lake build`, parses the log for revertable
# privatizations via bulk_revert.py, applies them, amends the WIP commit,
# and rebuilds. Stops on the first passing build, on no-more-reverts, or
# at the iteration cap (default 200, overridable with ITER_CAP).
#
# Build logs and per-iter revert reports go to $WORK_LOGDIR (default
# data/work/iterate/).

set -uo pipefail

# Resolve repo paths relative to this script.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

MATHLIB="${MATHLIB_DIR:-$HOME/mathlib4}"
PYTHON="${PYTHON:-python3}"
LOGDIR="${WORK_LOGDIR:-$REPO_ROOT/data/work/iterate}"
ITER_CAP="${ITER_CAP:-200}"

if [ ! -d "$MATHLIB" ]; then
  echo "error: MATHLIB_DIR ($MATHLIB) does not exist" >&2
  exit 1
fi

mkdir -p "$LOGDIR"

export PYTHONPATH="$REPO_ROOT/pipeline/src${PYTHONPATH:+:$PYTHONPATH}"

cd "$MATHLIB"
n_iter=0
total_reverts=0

while [ "$n_iter" -lt "$ITER_CAP" ]; do
  n_iter=$((n_iter + 1))
  log="$LOGDIR/build_$(printf '%03d' $n_iter).log"

  printf "[iter %3d / %s] build...  " "$n_iter" "$(date '+%H:%M:%S')"
  start=$(date +%s)
  if lake build > "$log" 2>&1; then
    end=$(date +%s)
    printf "✓ PASSES (%ds, total reverts=%d)\n" $((end - start)) $total_reverts
    exit 0
  fi
  end=$(date +%s)

  rev_log="$LOGDIR/revert_$(printf '%03d' $n_iter).log"
  if "$PYTHON" "$REPO_ROOT/pipeline/src/bulk_revert.py" "$log" > "$rev_log" 2>&1; then
    n_actual=$(grep '^reverted:' "$rev_log" | head -1 | awk '{print $2}')
    n_actual="${n_actual:-0}"
    total_reverts=$((total_reverts + n_actual))
    printf "✗ failed (%ds), reverted %s, n_errors=%s\n" \
      $((end - start)) "$n_actual" \
      "$(grep -c '^error:' "$log" || echo '?')"
  else
    printf "✗ failed (%ds), revert script returned no reverts — STUCK\n" $((end - start))
    head -30 "$log"
    exit 1
  fi

  git commit --amend --no-edit -a > /dev/null 2>&1
done

echo "[ITER CAP $ITER_CAP reached without convergence]"
exit 1
