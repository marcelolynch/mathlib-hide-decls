#!/usr/bin/env bash
# cache_demo.sh — empirical cache-cut demonstration.
#
# Setup assumed:
#   - $MATHLIB_DIR points at a mathlib4 worktree with the experiment branch
#     checked out.
#   - Mathlib.Tactic.Translate.Core has 13 privatized decls (the experiment
#     branch state).
#   - Mathlib.Tactic.Translate.{ToAdditive,ToDual} are built and current.
#
# Steps:
#   1. Snapshot olean hashes for Core + ToAdditive + ToDual.
#   2. In-place body edit (no line shifts) inside the `etaExpandN` private
#      decl: a single-word swap in a string literal.
#   3. Rebuild Mathlib.Tactic.Translate.Core only.
#   4. Snapshot hashes again.
#   5. Rebuild ToAdditive and ToDual; expect cache-hit (no actual work).
#   6. Revert the body edit.
#
# Expected outcome:
#   Core.olean.hash         UNCHANGED  (public surface untouched)
#   Core.olean.private.hash CHANGED    (private body changed)
#   ToAdditive.olean.hash   UNCHANGED  (cache-hit)
#   ToDual.olean.hash       UNCHANGED  (cache-hit)
set -euo pipefail

MATHLIB="${MATHLIB_DIR:-$HOME/mathlib4}"
if [ ! -d "$MATHLIB" ]; then
  echo "error: MATHLIB_DIR ($MATHLIB) does not exist" >&2
  exit 1
fi
cd "$MATHLIB"

CORE=.lake/build/lib/lean/Mathlib/Tactic/Translate/Core.olean
TOAD=.lake/build/lib/lean/Mathlib/Tactic/Translate/ToAdditive.olean
TODL=.lake/build/lib/lean/Mathlib/Tactic/Translate/ToDual.olean
F=Mathlib/Tactic/Translate/Core.lean

snapshot() {
  local label=$1
  echo "==== $label ===="
  for f in "$CORE" "$TOAD" "$TODL"; do
    name=$(basename "$f")
    for ext in .hash .private.hash .server.hash; do
      printf "  %-30s %-14s = %s\n" "$name" "$ext" "$(cat "$f$ext")"
    done
  done
}

# Pre-flight: make sure baseline is built
echo "==== Pre-flight: baseline build ===="
lake build Mathlib.Tactic.Translate.Core Mathlib.Tactic.Translate.ToAdditive Mathlib.Tactic.Translate.ToDual

snapshot "STATE A: before private-body edit"
cp "$F" /tmp/Translate-Core.before-cache-demo

# Edit: in-place word swap inside a private decl body. No line shifts.
# Original line in etaExpandN body:   throwError "{e} is not a function of arity at least {n}"
# Edited:                              throwError "{e} is not a function of count at least {n}"
sed -i.demo-bak 's/is not a function of arity at least/is not a function of count at least/' "$F"
echo ""
echo "==== diff after edit ===="
diff "$F.demo-bak" "$F" || true
rm -f "$F.demo-bak"
echo ""

# Rebuild only Core
echo "==== Rebuild Core ===="
lake build Mathlib.Tactic.Translate.Core
snapshot "STATE B: after private-body edit + Core rebuild"

# Try downstream rebuild — should cache-hit
echo ""
echo "==== Try ToAdditive (expect cache-hit, no work) ===="
lake build Mathlib.Tactic.Translate.ToAdditive
echo ""
echo "==== Try ToDual (expect cache-hit, no work) ===="
lake build Mathlib.Tactic.Translate.ToDual

snapshot "STATE C: after downstream re-check"

# Revert the demo edit
cp /tmp/Translate-Core.before-cache-demo "$F"
echo ""
echo "==== Reverted; final diff vs HEAD ===="
git diff --stat "$F"
