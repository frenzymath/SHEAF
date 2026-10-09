#!/bin/bash
# Land one file from a sandbox into the library.
# Usage: SHEAF_GROUP=<group> tools/land.sh <sandbox file> <library file>
#
# Steps: write the file into the library; if it changes what other modules see (a definition, a statement, an
# instance or attribute, a removed import), compile it in its place; run import_prune_check.py; hand the landing to
# the global build (landing.py), which verifies it together with everything that depends on it. A change to proofs
# alone is not compiled again: the worker's single-file compile and the lead's review are its check, and the build
# confirms it.
# From the write until the checks have passed the landing is "in flight": a global build started then takes the
# previous version of the file. If a check fails, the previous version is put back and the exit code is non-zero:
# 1 does not compile, 2 usage, 3 refused by a check.
# A landing that changes what other modules see is of kind `interface` and makes the global build start over at once.
# When the change needs other modules adapted, land them all together with land_set.sh.
set -u
source "$(dirname "$0")/sheaf_env.sh"
: "${SHEAF_GROUP:?set SHEAF_GROUP}"
SRC=$(realpath "${1:?usage: land.sh <sandbox file> <library file>}"); DST=$(realpath -m "${2:?usage: land.sh <sandbox file> <library file>}")
case "$SRC" in "$SHEAF_LEAN/.sandbox/$SHEAF_GROUP/"*) ;; *) echo "The sandbox file must be under lean/.sandbox/$SHEAF_GROUP/"; exit 2;; esac
ok=0; for d in $SHEAF_LIB; do case "$DST" in "$SHEAF_LEAN/$d/"*|"$SHEAF_LEAN/$d.lean") ok=1;; esac; done
[ $ok = 1 ] || { echo "The target must be in the library ($SHEAF_LIB under lean/)"; exit 2; }
REL=${DST#"$SHEAF_LEAN/"}; MOD=${REL%.lean}; MOD=${MOD//\//.}
T="$(dirname "$0")"

ID=$(python3 "$T/landing.py" begin "$SHEAF_GROUP" "$REL") || exit 3
OLD="$SHEAF_ROOT/local/builds/backup/$ID/$REL"; [ -e "$OLD" ] || OLD=/dev/null
mkdir -p "$(dirname "$DST")"; cp "$SRC" "$DST"
giveup() { python3 "$T/landing.py" abort "$ID"; echo "$1; the library is unchanged."; exit "$2"; }

CHANGES=$(python3 - "$T" "$OLD" "$DST" <<'PY'
import pathlib, sys
sys.path.insert(0, sys.argv[1]); import leanindex
old = pathlib.Path(sys.argv[2]).read_text() if sys.argv[2] != "/dev/null" else ""
new = pathlib.Path(sys.argv[3]).read_text() if pathlib.Path(sys.argv[3]).is_file() else ""
print("\n".join(leanindex.interface_changes(old, new)))
PY
)
if [ -n "$CHANGES" ]; then
  echo "Changes what other modules see: $CHANGES"; echo "Compiling $MOD in the library"
  "$T/lean_file.sh" "$DST" || giveup "It does not compile in the library" 1
fi
python3 "$T/import_prune_check.py" "$MOD" "$OLD" "$DST" || giveup "Refused (see above)" 3
KIND=$(python3 "$T/landing.py" finish "$ID") || exit 2
echo "Landed $MOD as landing $ID ($KIND). The next global build verifies it; see tools/landing.py status $ID."
