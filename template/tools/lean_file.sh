#!/bin/bash
# Compile one Lean file, with 2 threads and a time limit.
# Usage: SHEAF_GROUP=<group> tools/lean_file.sh <file.lean>
#
# - The time limit is SHEAF_FILE_TIMEOUT, default 60 s.
# - A library file compiled here writes its .olean into the group's private mirror local/build/<group>/ of the shared build,
#   so the group's later compiles can import a module it has just landed, before the next global build.
#   The shared build itself is only written when a green global build is published (build.py); a compile waits while
#   that is happening, and one that fails while it happened is run again once.
source "$(dirname "$0")/sheaf_env.sh"
F=${1:?usage: tools/lean_file.sh <file.lean>}; [ -f "$F" ] || { echo "no such file: $F"; exit 2; }
F=$(realpath "$F")
LP=$(cd "$SHEAF_LEAN" && lake env printenv LEAN_PATH) || { echo "lake env failed in $SHEAF_LEAN"; exit 2; }
OUT=()
refresh_mirror() {
  # Link what the shared build has and the mirror lacks; where the shared build is newer than a file the group
  # compiled itself, the shared one is the verified one and replaces it; drop links to modules that are gone.
  [ ! -e "$M/.stamp" ] || [ "$SHEAF_BUILD" -nt "$M/.stamp" ] || return 0
  mkdir -p "$M"
  while IFS= read -r own; do
    s="$SHEAF_BUILD/${own#"$M"/}"
    [ -e "$s" ] && [ "$s" -nt "$own" ] && ln -sf "$s" "$own"
  done < <(find "$M" -type f \( -name '*.olean' -o -name '*.ilean' \) 2>/dev/null)
  find "$M" -xtype l -delete 2>/dev/null
  for x in "$SHEAF_BUILD"/*; do [ -e "$x" ] && ionice -c3 cp -asn "$x" "$M/" 2>/dev/null; done
  touch "$M/.stamp"
}
if [ -n "${SHEAF_GROUP:-}" ]; then
  M="$SHEAF_ROOT/local/build/$SHEAF_GROUP"
  refresh_mirror
  LP=${LP//$SHEAF_BUILD/$M}
  case "$F" in
    "$SHEAF_LEAN"/.sandbox/*) ;;
    "$SHEAF_LEAN"/*) R=${F#"$SHEAF_LEAN"/}; R=${R%.lean}; mkdir -p "$M/$(dirname "$R")"
                     OUT=(-o "$M/$R.olean" -i "$M/$R.ilean");;
  esac
fi
compile() {
  local n=0
  while [ -e "$SHEAF_ROOT/local/PUBLISHING" ] && [ $n -lt 60 ]; do sleep 2; n=$((n + 1)); done
  [ -n "${SHEAF_GROUP:-}" ] && refresh_mirror
  [ ${#OUT[@]} -gt 0 ] && rm -f "${OUT[1]}" "${OUT[3]}"
  ( cd "$SHEAF_LEAN" && LEAN_PATH="$LP" timeout "${SHEAF_FILE_TIMEOUT:-60}" env LEAN_NUM_THREADS=2 nice -n 19 \
      lean -R "$SHEAF_LEAN" "${OUT[@]}" "$F" )
}
T0=$(date +%s.%N); START=$(mktemp); compile; rc=$?
if [ $rc -ne 0 ] && [ $rc -ne 124 ] && [ "$SHEAF_ROOT/local/builds/published" -nt "$START" ]; then
  echo "A global build was published during the compile; compiling again."; compile; rc=$?
fi
rm -f "$START"
DT=$(awk -v a="$(date +%s.%N)" -v b="$T0" 'BEGIN{printf "%.1f", a-b}')
if [ $rc -eq 124 ]; then
  echo "Timeout after ${SHEAF_FILE_TIMEOUT:-60} s: the cause is a definition the file uses; find it and change it."; exit 124
fi
echo "Compiled in ${DT} s"; exit $rc
