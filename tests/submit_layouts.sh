#!/bin/bash
# Scenario test of the submit commands of skills/compiling/SKILL.md: tools/submit_frozen.py (with and without --pr),
# tools/submit_pr.sh and tools/prs.py, with no Lean: a fake `lake` and `lean` stand in for the compiler. A file fails
# to compile when it contains the word BROKEN, or when it imports a module of which no .olean is on LEAN_PATH.
# Usage: tests/submit_layouts.sh <work dir>      (a directory that does not exist yet or is empty)
set -u
W=${1:?usage: tests/submit_layouts.sh <work dir>}
[ ! -e "$W" ] || [ -z "$(ls -A "$W")" ] || { echo "$W is not empty"; exit 2; }
mkdir -p "$W"; W=$(cd "$W" && pwd)
TEMPLATE=$(cd "$(dirname "$0")/../template" && pwd)
P="$W/my project"; cp -r "$TEMPLATE" "$P"; find "$P" -name __pycache__ -prune -exec rm -rf {} +
BUILD="$P/lean/.lake/build/lib/lean"
mkdir -p "$W/bin" "$P/lean/Paper" "$BUILD/Paper" "$P/local"
cat > "$W/bin/lake" <<'X'
#!/bin/bash
[ "$1 $2 $3" = "env printenv LEAN_PATH" ] && { echo "$PWD/.lake/build/lib/lean"; exit 0; }
echo "fake lake: $*" >&2; exit 1
X
cat > "$W/bin/lean" <<'X'
#!/bin/bash
f="${@: -1}"; grep -q BROKEN "$f" && { echo "$f:1:0: error: fake failure"; exit 1; }
for m in $(sed -n 's/^import \([A-Za-z.]*\)$/\1/p' "$f"); do
  found=; IFS=:; for d in $LEAN_PATH; do [ -e "$d/${m//.//}.olean" ] && found=1; done; unset IFS
  [ -n "$found" ] || { echo "$f: unknown module $m"; exit 1; }
done
for a in "$@"; do case "$a" in -o|-i) o=1;; *) [ "${o:-}" = 1 ] && { mkdir -p "$(dirname "$a")"; echo "built from $f" > "$a"; }; o=;; esac; done
exit 0
X
chmod +x "$W/bin/"*; export PATH="$W/bin:$PATH"
echo "SHEAF_LIB=Paper" > "$P/coord/sheaf.env"
echo 'name = "x"' > "$P/lean/lakefile.toml"
A='def fooBarDef : Nat := 1

theorem fooBarThm : fooBarDef = 1 := sorry
'
cd "$P"; T="$P/tools"; pass=0; fail=0
sb() { d="$P/lean/.sandbox/g1/$1/lean"; mkdir -p "$d/Paper"; echo "$d"; }
check() { # name expected-exit actual-exit condition
  if [ "$2" = "$3" ] && eval "$4"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1 (exit $3, wanted $2)"; echo "$OUT" | tail -5; fail=$((fail+1)); fi; }
reset() { printf '%s' "$A" > lean/Paper/A.lean; echo old > "$BUILD/Paper/A.olean"; rm -f lean/Paper/C.lean lean/Paper/D.lean "$BUILD"/Paper/[CD].*; cp lean/Paper/A.lean "$W/A.before"; }
STMT='s/fooBarDef = 1 :=/fooBarDef = 1 ∧ True :=/'

# frozen repository
reset; D=$(sb f1); sed 's/:= sorry/:= rfl/' lean/Paper/A.lean > "$D/Paper/A.lean"
OUT=$("$T/submit_frozen.py" g1 "$D" Paper/A.lean 2>&1); rc=$?
check "frozen: proof change is compiled and lands with its .olean" 0 $rc 'grep -q ":= rfl" lean/Paper/A.lean && grep -q "built from" "$BUILD/Paper/A.olean"'

reset; D=$(sb f2); sed 's/:= sorry/:= BROKEN/' lean/Paper/A.lean > "$D/Paper/A.lean"
OUT=$("$T/submit_frozen.py" g1 "$D" Paper/A.lean 2>&1); rc=$?
check "frozen: proof change that does not compile is refused" 1 $rc 'cmp -s lean/Paper/A.lean "$W/A.before" && grep -qx old "$BUILD/Paper/A.olean"'

reset; D=$(sb f3); sed "$STMT" lean/Paper/A.lean > "$D/Paper/A.lean"
OUT=$("$T/submit_frozen.py" g1 "$D" Paper/A.lean 2>&1); rc=$?
check "frozen: statement change is refused" 3 $rc 'cmp -s lean/Paper/A.lean "$W/A.before" && echo "$OUT" | grep -q frozen'

reset; D=$(sb f4); printf '%s\ntheorem addedThm : True := trivial\n' "$A" > "$D/Paper/A.lean"
printf 'import Paper.C\n\ntheorem dThm : True := cThm\n' > "$D/Paper/D.lean"
printf 'import Paper.A\n\ntheorem cThm : True := trivial\n' > "$D/Paper/C.lean"
OUT=$("$T/submit_frozen.py" g1 "$D" Paper/D.lean Paper/C.lean Paper/A.lean 2>&1); rc=$?
check "frozen: new files compile in import order, an added theorem is allowed" 0 $rc '[ -f lean/Paper/D.lean ] && [ -f "$BUILD/Paper/C.olean" ] && [ -f "$BUILD/Paper/D.ilean" ] && grep -q addedThm lean/Paper/A.lean'

reset; D=$(sb f5); printf 'import Paper.Missing\n\ntheorem eThm : True := trivial\n' > "$D/Paper/C.lean"
OUT=$("$T/submit_frozen.py" g1 "$D" Paper/C.lean 2>&1); rc=$?
check "frozen: a new file importing what does not exist is refused" 1 $rc '[ ! -f lean/Paper/C.lean ]'

reset; D=$(sb f6); sed 's/:= sorry/:= rfl/' lean/Paper/A.lean > "$D/Paper/A.lean"
( sleep 0.1; echo "-- edited meanwhile" >> lean/Paper/A.lean ) &
PATH="$W/slow:$PATH"; mkdir -p "$W/slow"; printf '#!/bin/bash\nsleep 0.5; exec %s "$@"\n' "$W/bin/lean" > "$W/slow/lean"; chmod +x "$W/slow/lean"
OUT=$("$T/submit_frozen.py" g1 "$D" Paper/A.lean 2>&1); rc=$?; wait
PATH=${PATH#"$W/slow:"}
check "frozen: a library file changed during the compile is not overwritten" 3 $rc 'grep -q "edited meanwhile" lean/Paper/A.lean && ! grep -q ":= rfl" lean/Paper/A.lean'

# pull requests
closer() { # wait for one open pull request, then close it
  for _ in $(seq 100); do id=$(ls local/prs/open 2>/dev/null | head -1); [ -n "$id" ] && break; sleep 0.1; done
  python3 "$T/prs.py" list > "$W/list.txt"; mkdir -p "$W/tree"; python3 "$T/prs.py" apply "$W/tree" "$id" > /dev/null
  python3 "$T/prs.py" close "$id" "$@"; }

reset; D=$(sb p1); sed "$STMT" lean/Paper/A.lean > "$D/Paper/A.lean"
closer merged & OUT=$(timeout 60 "$T/submit_frozen.py" --pr g1 "$D" Paper/A.lean 2>&1); rc=$?; wait
check "frozen --pr: statement change becomes a pull request; merged gives 0" 0 $rc 'grep -q "fooBarDef: \|fooBarThm" "$W/list.txt" && grep -q "∧ True" "$W/tree/Paper/A.lean" && [ -z "$(ls local/prs/open)" ]'

reset; D=$(sb p2); sed "$STMT" lean/Paper/A.lean > "$D/Paper/A.lean"
closer returned "breaks Paper.B" & OUT=$(timeout 60 "$T/submit_pr.sh" g1 "$D" Paper/A.lean 2>&1); rc=$?; wait
check "submit_pr: returned gives 1 with the reason" 1 $rc 'echo "$OUT" | grep -q "breaks Paper.B"'

reset; D=$(sb p3); sed 's/:= sorry/:= rfl/' lean/Paper/A.lean > "$D/Paper/A.lean"
OUT=$("$T/submit_frozen.py" --pr g1 "$D" Paper/A.lean 2>&1); rc=$?
check "frozen --pr: a proof change still lands directly" 0 $rc 'grep -q ":= rfl" lean/Paper/A.lean && [ -z "$(ls local/prs/open 2>/dev/null)" ]'

echo "$pass passed, $fail failed"
[ $fail = 0 ]
