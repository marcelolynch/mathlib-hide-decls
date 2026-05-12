#!/usr/bin/env bash
# bulk_no_expose_iterate.sh — drive the apply -> build -> revert loop for the
# tier-3 @[no_expose] bulk experiment.
#
# Assumes:
#   - MATHLIB_DIR points at a mathlib4 worktree.
#   - The script switches that worktree to a fresh branch
#     `experiment/bulk-no-expose-$(date +%Y%m%d)` based on origin/master.
#   - Pipeline data files (ranked_candidates.jsonl.gz, census_lean.jsonl.gz)
#     are populated under data/.
#
# Loop:
#   1. Apply @[no_expose] to all in-scope decls in the modules of the top-K
#      tier-3 hubs (bulk_no_expose_apply.py).
#   2. Commit.
#   3. lake build → if pass, commit and exit.
#   4. If fail, run bulk_no_expose_revert.py against the build log,
#      git commit --amend the file changes, and loop.
#   5. Stop on convergence or ITER_CAP iterations.
#
# Tunables (env):
#   BULK_NO_EXPOSE_TOP_K   default 1000 — number of tier-3 hubs to seed from
#   ITER_CAP               default 50   — max build-revert iterations
#   WORK_LOGDIR            default data/work/no_expose/iterate/

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

MATHLIB="${MATHLIB_DIR:-$HOME/mathlib4}"
PYTHON="${PYTHON:-python3}"
LOGDIR="${WORK_LOGDIR:-$REPO_ROOT/data/work/no_expose/iterate}"
ITER_CAP="${ITER_CAP:-50}"
BRANCH="${EXPERIMENT_BRANCH:-experiment/bulk-no-expose-$(date +%Y%m%d-%H%M)}"

if [ ! -d "$MATHLIB" ]; then
  echo "error: MATHLIB_DIR ($MATHLIB) does not exist" >&2
  exit 1
fi

mkdir -p "$LOGDIR"
rm -f "$REPO_ROOT/data/work/no_expose/manifest.jsonl"
rm -f "$REPO_ROOT/data/work/no_expose/skipped.jsonl"
rm -f "$REPO_ROOT/data/work/no_expose/reverted.jsonl"

export PYTHONPATH="$REPO_ROOT/pipeline/src${PYTHONPATH:+:$PYTHONPATH}"

# --- Step 1: prep branch ---
cd "$MATHLIB"
echo "[prep] fetching origin/master..."
git fetch origin master >/dev/null 2>&1 || true
echo "[prep] creating branch $BRANCH"
git switch -c "$BRANCH" origin/master >/dev/null 2>&1 || \
  { echo "branch $BRANCH already exists or master unreachable" >&2; exit 1; }

# --- Step 2: apply ---
echo "[apply] running bulk_no_expose_apply.py with TOP_K=${BULK_NO_EXPOSE_TOP_K:-1000}..."
"$PYTHON" "$REPO_ROOT/pipeline/src/bulk_no_expose_apply.py" \
  > "$LOGDIR/apply.log" 2>&1
n_applied=$(wc -l < "$REPO_ROOT/data/work/no_expose/manifest.jsonl" | tr -d ' ')
n_skipped=$(wc -l < "$REPO_ROOT/data/work/no_expose/skipped.jsonl" | tr -d ' ')
echo "[apply] applied=$n_applied skipped=$n_skipped"

if [ "$n_applied" -eq 0 ]; then
  echo "[apply] nothing applied — bailing"
  exit 1
fi

# Initial commit so amend can attach the iterate-revert deltas
git add -A
git -c user.email=marcelo.lynch@renphil.org -c user.name="Marcelo Lynch" \
  commit -m "WIP: bulk @[no_expose] applied to $n_applied defs (pre-revert)" \
  >/dev/null

# --- Step 3-4: build / revert loop ---
n_iter=0
total_reverts=0
last_n_errors=999999

while [ "$n_iter" -lt "$ITER_CAP" ]; do
  n_iter=$((n_iter + 1))
  log="$LOGDIR/build_$(printf '%03d' $n_iter).log"

  printf "[iter %3d / %s] build...  " "$n_iter" "$(date '+%H:%M:%S')"
  start=$(date +%s)
  if lake build > "$log" 2>&1; then
    end=$(date +%s)
    printf "✓ PASSES (%ds, total reverts=%d)\n" $((end - start)) $total_reverts
    # Final amend so the commit message reflects post-revert state
    n_alive=$(wc -l < "$REPO_ROOT/data/work/no_expose/manifest.jsonl" | tr -d ' ')
    git -c user.email=marcelo.lynch@renphil.org -c user.name="Marcelo Lynch" \
      commit --amend -m "experiment: bulk @[no_expose] applied to $n_alive defs

Converged at iteration $n_iter after $total_reverts reverts.
Seed: top-${BULK_NO_EXPOSE_TOP_K:-1000} tier-3 hubs by score from
mathlib-hide-decls.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>" \
      >/dev/null
    echo "[done] branch $BRANCH ready to push."
    exit 0
  fi
  end=$(date +%s)
  n_errors=$(grep -c '^error:' "$log" 2>/dev/null || echo 0)

  rev_log="$LOGDIR/revert_$(printf '%03d' $n_iter).log"
  if "$PYTHON" "$REPO_ROOT/pipeline/src/bulk_no_expose_revert.py" "$log" \
       > "$rev_log" 2>&1; then
    n_actual=$(grep '^reverted:' "$rev_log" | head -1 | awk '{print $2}')
    n_actual="${n_actual:-0}"
    total_reverts=$((total_reverts + n_actual))
    printf "✗ failed (%ds, errors=%d), reverted=%d, total=%d\n" \
      $((end - start)) "$n_errors" "$n_actual" "$total_reverts"
    if [ "$n_actual" -eq 0 ]; then
      echo "[stuck] revert script returned 0 — bailing"
      tail -30 "$log"
      exit 1
    fi
  else
    printf "✗ failed (%ds, errors=%d) — revert script error, see %s\n" \
      $((end - start)) "$n_errors" "$rev_log"
    exit 1
  fi

  git commit --amend --no-edit -a >/dev/null 2>&1
done

echo "[ITER CAP $ITER_CAP reached without convergence]"
exit 1
