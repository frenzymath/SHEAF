#!/bin/bash
# Check that every target statement in the library is exactly the one locked in lean/Challenge.lean.
# Usage: tools/target_types.sh check
# The target names are the theorems of lean/Challenge.lean. The script elaborates each target once under `Challenge` and
# once under `TargetsCheck` (which imports the library's target modules), compares the hashes of the elaborated types
# and universe parameters, and prints the axioms of each target in the library.
# Comparing elaborated types, not source text, also catches a change hidden behind `let … :=` or a changed notation.
# Needs up-to-date .olean files of Challenge and TargetsCheck, so run it after a green build.
# Exit 0: all agree. Exit 3: a target differs or is missing. Exit 2: setup problem.
set -u
source "$(dirname "$0")/sheaf_env.sh"
[ "${1:-}" = check ] || { echo "usage: tools/target_types.sh check"; exit 2; }
C="$SHEAF_LEAN/Challenge.lean"; [ -f "$C" ] || { echo "No lean/Challenge.lean yet: nothing to check."; exit 0; }
mapfile -t NAMES < <(grep -oP '^theorem\s+\K[^\s({\[:]+' "$C")
[ ${#NAMES[@]} -gt 0 ] || { echo "No theorems in lean/Challenge.lean"; exit 2; }
LIST=$(printf '`%s, ' "${NAMES[@]}"); LIST=${LIST%, }
D="$SHEAF_LEAN/.sandbox/_sheaf"; mkdir -p "$D"
for side in Challenge TargetsCheck; do
  cat > "$D/Types_$side.lean" <<LEAN
import Lean
import $side
open Lean in
#eval show CoreM Unit from do
  for n in [$LIST] do
    match (← getEnv).find? n with
    | some c => IO.println s!"TYPE {n} {hash c.type} {c.levelParams}"
    | none => IO.println s!"TYPE {n} MISSING"
LEAN
done
for n in "${NAMES[@]}"; do echo "#print axioms $n"; done >> "$D/Types_TargetsCheck.lean"
A=$("$(dirname "$0")/lean_file.sh" "$D/Types_Challenge.lean" 2>&1) || { echo "$A"; exit 2; }
B=$(SHEAF_FILE_TIMEOUT=${SHEAF_FILE_TIMEOUT:-300} "$(dirname "$0")/lean_file.sh" "$D/Types_TargetsCheck.lean" 2>&1) || { echo "$B"; exit 2; }
echo "$B" | grep -v -e '^TYPE' -e '^Compiled in'
if [ "$(echo "$A" | grep '^TYPE' | sort)" = "$(echo "$B" | grep '^TYPE' | sort)" ] && ! echo "$A" | grep -q MISSING; then
  echo "All ${#NAMES[@]} target statements agree with lean/Challenge.lean."; exit 0
fi
echo "Target statements differ from lean/Challenge.lean:"
diff <(echo "$A" | grep '^TYPE' | sort) <(echo "$B" | grep '^TYPE' | sort)
exit 3
