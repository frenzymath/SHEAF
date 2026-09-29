#!/bin/bash
# List the definitions that may be hollow: definitions, abbreviations, instances and opaque constants of the library
# that depend on `sorryAx` in any way. The list is of candidates. A definition that only refers to an unproved named
# theorem for a proof it needs is on the list and is not hollow; read each one and decide (AGENTS.md §5).
# Theorems are not listed.
# Usage: tools/hollow_defs.sh      (needs the .olean files of the last global build)
set -u
source "$(dirname "$0")/sheaf_env.sh"
D="$SHEAF_LEAN/.sandbox/_sheaf"; mkdir -p "$D"
PREFIXES=$(for d in $SHEAF_LIB; do printf '`%s, ' "$d"; done); PREFIXES=${PREFIXES%, }
cat > "$D/HollowDefs.lean" <<LEAN
import Lean
import TargetsCheck
open Lean in
run_cmd do
  let env ← getEnv
  let prefixes : List Name := [$PREFIXES]
  let mut n : Nat := 0
  for i in [0:env.header.moduleNames.size] do
    let m := env.header.moduleNames[i]!
    unless prefixes.any (·.isPrefixOf m) do continue
    for cn in env.header.moduleData[i]!.constNames do
      if cn.isInternal then continue
      match env.find? cn with
      | some (.defnInfo _) | some (.opaqueInfo _) =>
        n := n + 1
        let ax ← Lean.collectAxioms cn
        if ax.contains \`sorryAx then logInfo m!"CANDIDATE {cn} ({m})"
      | _ => pure ()
  logInfo m!"SCANNED {n} definitions"
LEAN
SHEAF_FILE_TIMEOUT=${SHEAF_FILE_TIMEOUT_SCAN:-1800} "$(dirname "$0")/lean_file.sh" "$D/HollowDefs.lean" 2>&1 | grep -E 'CANDIDATE|SCANNED|error|Timeout'
