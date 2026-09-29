#!/bin/bash
# Land a set of files at once. This is how a changed statement or definition lands, together with the modules
# adapted to it.
# Usage: SHEAF_GROUP=<group> tools/land_set.sh <set directory>
#   The set directory is under lean/.sandbox/<group>/ and mirrors paths relative to lean/;
#   a file whose first line is `-- DELETE` deletes that library file.
# Steps: write every file; compile the files of the set, in the order of their imports, each within the single-file
# limit; run import_prune_check.py on every file; hand the set to the global build as one interface landing
# (landing.py). The script does not build the modules downstream of the set: the maintainer's build starts over as
# soon as the set has landed and verifies all of them. If that build fails because of the set, the maintainer reverts
# the whole set, and tools/landing.py mine <group> shows it with the reason.
# From the write until the checks have passed the set is "in flight": a global build started then takes the previous
# version of its files. If a check fails, every file is put back.
# Exit codes: 1 a file does not compile, 2 usage, 3 refused by a check.
set -u
source "$(dirname "$0")/sheaf_env.sh"
: "${SHEAF_GROUP:?set SHEAF_GROUP}"
SET=$(realpath "${1:?usage: land_set.sh <set directory>}")
case "$SET" in "$SHEAF_LEAN/.sandbox/$SHEAF_GROUP/"*) ;; *) echo "The set directory must be under lean/.sandbox/$SHEAF_GROUP/"; exit 2;; esac
T="$(dirname "$0")"
mapfile -t FILES < <(cd "$SET" && find . -name '*.lean' -type f | sed 's#^\./##' | sort)
[ ${#FILES[@]} -gt 0 ] || { echo "No .lean files in $SET"; exit 2; }
for f in "${FILES[@]}"; do
  ok=0; for d in $SHEAF_LIB; do case "$f" in "$d"/*|"$d.lean") ok=1;; esac; done
  [ $ok = 1 ] || { echo "$f is not in the library ($SHEAF_LIB)"; exit 2; }
done
echo "${#FILES[@]} file(s) in the set"

ID=$(python3 "$T/landing.py" begin "$SHEAF_GROUP" "${FILES[@]}") || exit 3
BK="$SHEAF_ROOT/local/builds/backup/$ID"
for f in "${FILES[@]}"; do
  mkdir -p "$SHEAF_LEAN/$(dirname "$f")"
  if [ "$(head -c 9 "$SET/$f")" = "-- DELETE" ]; then rm -f "$SHEAF_LEAN/$f"; else cp "$SET/$f" "$SHEAF_LEAN/$f"; fi
done
giveup() { python3 "$T/landing.py" abort "$ID"; echo "$1; every file of the set was put back."; exit "$2"; }

mapfile -t ORDER < <(python3 "$T/landing.py" order "${FILES[@]}") || giveup "The set cannot be ordered" 3
for f in "${ORDER[@]}"; do
  echo "Compiling $f"
  "$T/lean_file.sh" "$SHEAF_LEAN/$f" || giveup "$f does not compile" 1
done
for f in "${FILES[@]}"; do
  old="$BK/$f"; [ -e "$old" ] || old=/dev/null
  new="$SHEAF_LEAN/$f"; [ -e "$new" ] || new=/dev/null
  m=${f%.lean}; python3 "$T/import_prune_check.py" "${m//\//.}" "$old" "$new" || giveup "Refused for $f" 3
done
python3 "$T/landing.py" finish "$ID" --set > /dev/null || exit 2
echo "Landed the set as landing $ID. The global build starts over now and verifies everything downstream;"
echo "follow it with tools/landing.py status $ID. If it fails because of the set, the whole set is reverted."
