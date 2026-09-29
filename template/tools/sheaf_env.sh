#!/bin/bash
# Sourced by the other tools. Sets:
#   SHEAF_ROOT   the project directory (the one holding tools/)
#   SHEAF_LEAN   the Lake project (lean/, a directory or a link; SHEAF_TREE, set by build.py, selects the build copy)
#   SHEAF_LIB    the library's top-level source directories under lean/, space separated (from coord/sheaf.env)
#   SHEAF_BUILD  the shared build output, lean/.lake/build/lib/lean
SHEAF_ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SHEAF_LEAN=$(cd "${SHEAF_TREE:-$SHEAF_ROOT/lean}" 2>/dev/null && pwd -P) || { echo "sheaf: no Lean project in ${SHEAF_TREE:-$SHEAF_ROOT/lean}" >&2; exit 2; }
# Settings: coord/sheaf.env for the project, then coord/machines/<host name>.env for this machine.
for _f in "$SHEAF_ROOT/coord/sheaf.env" "$SHEAF_ROOT/coord/machines/$(hostname).env"; do
  [ -f "$_f" ] && { set -a; source "$_f"; set +a; }
done
: "${SHEAF_LIB:?set SHEAF_LIB in coord/sheaf.env}"
SHEAF_BUILD=$SHEAF_LEAN/.lake/build/lib/lean
export SHEAF_ROOT SHEAF_LEAN SHEAF_LIB SHEAF_BUILD
