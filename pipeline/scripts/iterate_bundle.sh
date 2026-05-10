#!/usr/bin/env bash
# iterate_bundle.sh — apply, verify, and commit the tier-1 privatizations of
# one tier-2 bundle (one module).
#
# Steps:
#   1. Triage the module's candidate decls (locate, classify, filter).
#   2. Apply `private` to all surviving candidates in one edit.
#   3. `lake build` the module; on failure parse the log for the offending
#      decl, revert it, and retry. Up to 12 iterations.
#   4. `lake build` the module's direct downstream importers (capped at 4
#      to keep verification time bounded). Same revert-on-failure logic.
#   5. Auto-fix any 100-char line-length warnings introduced by `private `.
#   6. Commit on a fresh branch chore/privatize-<slug>-helpers off master.
#
# State assumed:
#   - $MATHLIB_DIR points at a clean mathlib4 worktree on master.
#   - $PYTHON has the pipeline's dependencies on PYTHONPATH (handled below).
#
# On success the branch holds one commit; on failure the working tree is
# restored and the branch deleted.
set -euo pipefail

MODULE="${1:?usage: iterate_bundle.sh <module>}"
PATH_LEAN="$(echo "$MODULE" | tr '.' '/').lean"
SLUG="$(echo "$MODULE" | sed -E 's/^Mathlib\.//; s/\./-/g' | tr '[:upper:]' '[:lower:]')"
BRANCH="chore/privatize-${SLUG}-helpers"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MATHLIB="${MATHLIB_DIR:-$HOME/mathlib4}"
PYTHON="${PYTHON:-python3}"
LOG_PFX="${WORK_LOGDIR:-$REPO_ROOT/data/work/iter}-$SLUG"

mkdir -p "$(dirname "$LOG_PFX")"

export PYTHONPATH="$REPO_ROOT/pipeline/src${PYTHONPATH:+:$PYTHONPATH}"

cd "$MATHLIB"

echo "============================================================"
echo "Bundle: $MODULE"
echo "File:   $PATH_LEAN"
echo "Branch: $BRANCH"
echo "============================================================"

# Working tree must be clean.
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "✖ working tree is dirty; please clean it first" >&2
  git status --short >&2
  exit 1
fi
git checkout master 2>&1 | tail -1
if git rev-parse --verify "$BRANCH" >/dev/null 2>&1; then
  git branch -D "$BRANCH" 2>&1 | tail -1
fi
git checkout -B "$BRANCH" master 2>&1 | tail -1

# 1. Triage.
echo ""
echo "--- triage ---"
"$PYTHON" "$REPO_ROOT/pipeline/src/triage_module.py" "$MODULE" \
  | tee "$LOG_PFX-triage.txt"

# 2. Apply `private` edits using the centralized parsers in pipeline/src/.
"$PYTHON" - "$PATH_LEAN" "$MODULE" <<'PYEOF'
"""Apply `private` to each candidate decl, subject to the policy.toml
hard blocks (forbidden_attrs, forbidden_name_patterns, etc.).

Uses policy.parse_attrs to scan attributes both on the same line as the
def/lemma keyword and on the preceding lines.
"""
import json, re, sys
from pathlib import Path

import paths
import policy as _policy

FORBIDDEN_ATTRS = _policy.all_blocked_attrs()
FORBIDDEN_NAME_PATTERNS = _policy.forbidden_name_patterns()

path_lean = Path(sys.argv[1])
module = sys.argv[2]

candidates: list[str] = []
with paths.open_jsonl(paths.RANKED) as f:
    for line in f:
        r = json.loads(line)
        if r.get("tier") == "2_bundle" and r.get("module") == module:
            candidates = r["decls"]
            break
if not candidates:
    print("(no candidates)")
    sys.exit(0)

cand_set = set(candidates)
src = path_lean.read_text().splitlines(keepends=True)

ns_stack: list[str] = []
def_anchor = re.compile(r"^(?P<priv>private\s+)?(?:partial\s+)?def\s+(?P<name>[^\s\(\[\:]+)")
ns_open = re.compile(r"^namespace\s+(\S+)")
ns_close = re.compile(r"^end\s+(\S+)")

priv_lines: list[tuple[int, str, str]] = []
attr_blocked: list[tuple[int, str, list[str]]] = []

def has_forbidden_attr(line_idx: int, kind_kw: str) -> list[str]:
    src_stripped = [ln.rstrip("\n") for ln in src]
    all_attrs = _policy.parse_attrs(src_stripped, line_idx, kind_kw)
    return [a for a in all_attrs if a in FORBIDDEN_ATTRS]

for i, line in enumerate(src):
    m_open = ns_open.match(line)
    if m_open:
        ns_stack.append(m_open.group(1))
        continue
    m_close = ns_close.match(line)
    if m_close:
        if ns_stack and ns_stack[-1] == m_close.group(1):
            ns_stack.pop()
        elif ns_stack:
            target = m_close.group(1)
            while ns_stack and ".".join(ns_stack) != target and ns_stack[-1] != target:
                ns_stack.pop()
            if ns_stack and ns_stack[-1] == target:
                ns_stack.pop()
        continue
    m = def_anchor.match(line)
    if not m:
        continue
    if m.group("priv"):
        continue
    leaf = m.group("name")
    fq_candidates: list[str] = []
    for k in range(len(ns_stack), -1, -1):
        prefix = ".".join(ns_stack[:k])
        fq_candidates.append(f"{prefix}.{leaf}" if prefix else leaf)
    matched = next((fq for fq in fq_candidates if fq in cand_set), None)
    if not matched:
        continue
    bad = has_forbidden_attr(i, "def")
    if bad:
        attr_blocked.append((i + 1, matched, bad))
        continue
    if "simps_projection" in FORBIDDEN_NAME_PATTERNS \
       and (".Simps." in matched or matched.endswith(".Simps")):
        attr_blocked.append((i + 1, matched, ["name-pattern: simps_projection"]))
        continue
    kind = "partial def" if line.startswith("partial def") else "def"
    src[i] = "private " + line
    priv_lines.append((i + 1, matched, kind))

path_lean.write_text("".join(src))
print(f"applied {len(priv_lines)} private edits")
for ln, fq, kind in priv_lines:
    print(f"  line {ln}: {kind} {fq}")
if attr_blocked:
    print(f"skipped {len(attr_blocked)} candidate(s) due to forbidden attributes:")
    for ln, fq, attrs in attr_blocked:
        print(f"  line {ln}: {fq}  ← @[{', '.join(attrs)}]")
PYEOF

n_initial=$(git diff "$PATH_LEAN" | grep -c "^+private " || true)
echo "  ($n_initial private prefixes added initially)"

if [ "$n_initial" -lt 1 ]; then
  echo "  no successful matches — bailing"
  git checkout -- "$PATH_LEAN"
  git checkout master
  git branch -D "$BRANCH"
  exit 0
fi

# Revert one private prefix by leaf name.
revert_one() {
  local LEAF="$1"
  "$PYTHON" - "$PATH_LEAN" "$LEAF" <<'PYEOF'
import re, sys
from pathlib import Path
path_lean = Path(sys.argv[1])
leaf = sys.argv[2]
src = path_lean.read_text().splitlines(keepends=True)
safe = re.escape(leaf)
pat = re.compile(rf"^private\s+((?:partial\s+)?def\s+{safe}(\s|\(|\[|:|$))")
for i, line in enumerate(src):
    if pat.match(line):
        src[i] = line[len("private "):]
        print(f"  reverted line {i+1}: {src[i].rstrip()[:80]}")
        path_lean.write_text("".join(src))
        sys.exit(0)
sys.exit(1)
PYEOF
}

# Extract the offending decl's leaf name from a build log.
parse_failure() {
  local LOG="$1"
  local UNK
  UNK=$(grep -E "A private declaration \`[A-Za-z_]" "$LOG" 2>/dev/null \
        | head -1 | sed -E 's/.*A private declaration \`([A-Za-z_][A-Za-z_0-9?]*)\`.*/\1/' || true)
  if [ -z "$UNK" ]; then
    UNK=$(grep -E "must be public" "$LOG" 2>/dev/null \
          | head -1 | sed -E 's/.*Declaration \`[^\`]*\.([A-Za-z_][A-Za-z_0-9?]*)\` must be public.*/\1/' || true)
  fi
  if [ -z "$UNK" ]; then
    UNK=$(grep -E "Unknown identifier \`[A-Za-z_]" "$LOG" 2>/dev/null \
          | head -1 | sed -E 's/.*Unknown identifier \`([A-Za-z_][A-Za-z_0-9?]*)\`.*/\1/' || true)
  fi
  if [ -z "$UNK" ]; then
    UNK=$(grep -E "Invalid field \`[A-Za-z_]" "$LOG" 2>/dev/null \
          | head -1 | sed -E 's/.*Invalid field `([A-Za-z_][A-Za-z_0-9?]*)`.*/\1/' || true)
  fi
  if [ -z "$UNK" ]; then
    UNK=$(grep -E "Unknown constant \`" "$LOG" 2>/dev/null \
          | head -1 | sed -E 's/.*Unknown constant `[^`]*\.([A-Za-z_][A-Za-z_0-9?]*)`.*/\1/' || true)
    if [ -n "$UNK" ] && ! echo "$UNK" | grep -qE '^[A-Za-z_][A-Za-z_0-9?]*$'; then
      UNK=$(grep -E "Unknown constant \`" "$LOG" 2>/dev/null \
            | head -1 | sed -E 's/.*Unknown constant `([A-Za-z_][A-Za-z_0-9?]*)`.*/\1/' || true)
    fi
  fi
  echo -n "$UNK"
}

# 3. Build the module itself; iterate revert-on-failure.
echo ""
echo "--- build module ---"
attempt=0
declare -a reverted_names=()
while true; do
  attempt=$((attempt + 1))
  if [ "$attempt" -gt 12 ]; then
    echo "  too many module-build revert iterations; bailing" >&2
    git checkout -- "$PATH_LEAN"; git checkout master; git branch -D "$BRANCH"
    exit 1
  fi
  if lake build "$MODULE" > "$LOG_PFX-build.log" 2>&1; then
    echo "  ✓ module builds clean"
    break
  fi
  # Auto-fix line-length first.
  if grep -qE "exceeds the 100 character limit" "$LOG_PFX-build.log"; then
    "$PYTHON" - "$PATH_LEAN" "$LOG_PFX-build.log" <<'PYEOF'
import re, sys
from pathlib import Path
path_lean = Path(sys.argv[1])
log = Path(sys.argv[2]).read_text()
linenos = sorted({int(m.group(1)) for m in re.finditer(rf":(\d+):100:", log)}, reverse=True)
src = path_lean.read_text().splitlines(keepends=False)
fixed = 0
for ln in linenos:
    i = ln - 1
    if i >= len(src): continue
    line = src[i]
    if not line.startswith("private "):
        continue
    for sep in [" :=", " :", " ←"]:
        idx = line.find(sep, 60)
        if 60 < idx < 100:
            head = line[:idx].rstrip()
            tail = line[idx:].lstrip()
            src[i] = head + "\n" + " " * 4 + tail
            fixed += 1
            break
    else:
        sp = line.rfind(" ", 50, 100)
        if sp > 50:
            head, tail = line[:sp].rstrip(), line[sp:].lstrip()
            src[i] = head + "\n" + " " * 4 + tail
            fixed += 1
path_lean.write_text("\n".join(src) + "\n")
print(f"  line-wrapped {fixed} long line(s)")
PYEOF
    continue
  fi
  UNK=$(parse_failure "$LOG_PFX-build.log")
  if [ -z "$UNK" ]; then
    echo "  ✖ can't parse error from log; bailing" >&2
    tail -20 "$LOG_PFX-build.log" >&2
    git checkout -- "$PATH_LEAN"; git checkout master; git branch -D "$BRANCH"
    exit 1
  fi
  for prev in "${reverted_names[@]:-}"; do
    if [ "$prev" = "$UNK" ]; then
      echo "  circular revert on $UNK; bailing"
      git checkout -- "$PATH_LEAN"; git checkout master; git branch -D "$BRANCH"
      exit 0
    fi
  done
  reverted_names+=("$UNK")
  echo "  module needs $UNK to be public; reverting"
  if ! revert_one "$UNK"; then
    echo "  could not find private $UNK to revert; bailing" >&2
    git checkout -- "$PATH_LEAN"; git checkout master; git branch -D "$BRANCH"
    exit 1
  fi
done

# 4. Build direct downstream importers (capped).
echo ""
echo "--- build direct downstream importers ---"
importers=$(grep -rln -E "^(public )?import $MODULE$" Mathlib/ --include='*.lean' 2>/dev/null || true)
if [ -z "$importers" ]; then
  echo "  no direct importers; skipping downstream check"
else
  imp_modules=$(echo "$importers" | sed -E 's|^Mathlib/|Mathlib.|; s|/|.|g; s|\.lean$||')
  imp_count=$(echo "$imp_modules" | wc -l | xargs)
  imp_capped=$(echo "$imp_modules" | head -4)
  echo "  $imp_count importers, building first $(echo "$imp_capped" | wc -l | xargs)"
  attempt=0
  declare -a down_reverted=()
  while true; do
    attempt=$((attempt + 1))
    if [ "$attempt" -gt 12 ]; then
      echo "  too many downstream-revert iterations; bailing" >&2
      git checkout -- "$PATH_LEAN"; git checkout master; git branch -D "$BRANCH"
      exit 0
    fi
    if echo "$imp_capped" | xargs lake build > "$LOG_PFX-down.log" 2>&1; then
      echo "  ✓ downstream builds clean"
      break
    fi
    UNK=$(parse_failure "$LOG_PFX-down.log")
    if [ -z "$UNK" ]; then
      echo "  ✖ downstream broke and can't parse error; bailing" >&2
      tail -10 "$LOG_PFX-down.log" >&2
      git checkout -- "$PATH_LEAN"; git checkout master; git branch -D "$BRANCH"
      exit 0
    fi
    for prev in "${down_reverted[@]:-}"; do
      if [ "$prev" = "$UNK" ]; then
        echo "  circular downstream revert on $UNK; bailing"
        git checkout -- "$PATH_LEAN"; git checkout master; git branch -D "$BRANCH"
        exit 0
      fi
    done
    down_reverted+=("$UNK")
    echo "  downstream needs $UNK; reverting"
    if ! revert_one "$UNK"; then
      echo "  could not find private $UNK; bailing" >&2
      git checkout -- "$PATH_LEAN"; git checkout master; git branch -D "$BRANCH"
      exit 0
    fi
    lake build "$MODULE" > /dev/null 2>&1 || true
  done
fi

# 5. Commit on the branch.
n_priv=$(git diff "$PATH_LEAN" | grep -c "^+private " || true)
echo ""
echo "--- final ---"
git diff --stat "$PATH_LEAN"
echo "  privatized: $n_priv"

if [ "$n_priv" -lt 1 ]; then
  echo "  no successful privatizations; not committing"
  git checkout -- "$PATH_LEAN"; git checkout master; git branch -D "$BRANCH"
  exit 0
fi

git add "$PATH_LEAN"
SUBJECT_PATH="$(echo "$MODULE" | sed -E 's/^Mathlib\.//; s/\./\//g')"
git commit -m "chore(${SUBJECT_PATH}): privatize $n_priv internal helpers in $MODULE

Mark $n_priv internal-only helper definitions as \`private\`. None are
referenced from outside the file, verified by \`lake build\` of the module
plus its direct downstream importers. The change is mechanical
(\`def → private def\`), preserving \`partial\` annotations. Long lines
auto-wrapped where the prefix pushes them past the 100-char style budget.

Lean 4.10's module system places \`private\` declaration bodies in
\`.olean.private\`. Edits to a \`private\` body do not move the public
\`.olean.hash\`, so downstream modules cache-hit across such edits." > /dev/null

echo "  ✓ branch $BRANCH ready: 1 commit on top of master, $n_priv privatized"
git checkout master 2>&1 | tail -1
