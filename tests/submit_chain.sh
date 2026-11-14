#!/bin/bash
# Scenario test of the default submit command (tools/submit.sh -> land.sh / land_set.sh -> landing.py and
# import_prune_check.py), with no Lean: a fake `lake` and `lean` stand in for the compiler, and a file fails to
# compile when it contains the word BROKEN. It checks what lands, what is put back and the exit codes.
# Usage: tests/submit_chain.sh <work dir>      (a directory that does not exist yet or is empty)
set -u
W=${1:?usage: tests/submit_chain.sh <work dir>}
[ ! -e "$W" ] || [ -z "$(ls -A "$W")" ] || { echo "$W is not empty"; exit 2; }
mkdir -p "$W"; W=$(cd "$W" && pwd)
TEMPLATE=$(cd "$(dirname "$0")/../template" && pwd)
P="$W/my project"; cp -r "$TEMPLATE" "$P"; find "$P" -name __pycache__ -prune -exec rm -rf {} +
mkdir -p "$W/bin" "$P/lean/Paper" "$P/lean/.lake/build/lib/lean"
cat > "$W/bin/lake" <<'X'
#!/bin/bash
[ "$1 $2 $3" = "env printenv LEAN_PATH" ] && { echo "$PWD/.lake/build/lib/lean"; exit 0; }
echo "fake lake: $*" >&2; exit 1
X
cat > "$W/bin/lean" <<'X'
#!/bin/bash
f="${@: -1}"; grep -q BROKEN "$f" && { echo "$f:1:0: error: fake failure"; exit 1; }
for a in "$@"; do case "$a" in -o) o=1;; *) [ "${o:-}" = 1 ] && { mkdir -p "$(dirname "$a")"; : > "$a"; }; o=;; esac; done
exit 0
X
chmod +x "$W/bin/"*; export PATH="$W/bin:$PATH"
echo "SHEAF_LIB=Paper" > "$P/coord/sheaf.env"
echo 'name = "x"' > "$P/lean/lakefile.toml"
A='def fooBarDef : Nat := 1

theorem fooBarThm : fooBarDef = 1 := rfl
'
B='import Paper.A

theorem bazQuxThm : fooBarDef = 1 := fooBarThm
'
printf '%s' "$A" > "$P/lean/Paper/A.lean"; printf '%s' "$B" > "$P/lean/Paper/B.lean"
cd "$P"; T="$P/tools"; pass=0; fail=0
sb() { d="$P/lean/.sandbox/g1/$1/lean"; mkdir -p "$d/Paper"; echo "$d"; }
check() { # name expected-exit actual-exit condition
  if [ "$2" = "$3" ] && eval "$4"; then echo "PASS $1"; pass=$((pass+1)); else echo "FAIL $1 (exit $3, wanted $2)"; echo "$OUT" | tail -5; fail=$((fail+1)); fi; }

reset() { printf '%s' "$A" > lean/Paper/A.lean; printf '%s' "$B" > lean/Paper/B.lean; rm -f lean/Paper/C.lean; cp lean/Paper/A.lean "$W/A.before"; cp lean/Paper/B.lean "$W/B.before"; }
STMT='s/fooBarDef = 1 :=/fooBarDef = 1 ∧ True :=/'

# 1. proof-only change of one file
reset; D=$(sb t1); printf '%s' "${A/:= rfl/:= by rfl}" > "$D/Paper/A.lean"
OUT=$("$T/submit.sh" g1 "$D" Paper/A.lean 2>&1); rc=$?
check "proof change lands without a compile" 0 $rc 'grep -q "by rfl" lean/Paper/A.lean && echo "$OUT" | grep -q "(proof)" && ! echo "$OUT" | grep -q Compiling'

# 2. interface change (a statement) that compiles
reset; D=$(sb t2); sed "$STMT" lean/Paper/A.lean > "$D/Paper/A.lean"
OUT=$("$T/submit.sh" g1 "$D" Paper/A.lean 2>&1); rc=$?
check "statement change is compiled and lands as interface" 0 $rc 'grep -q "∧ True" lean/Paper/A.lean && echo "$OUT" | grep -q "(interface)" && echo "$OUT" | grep -q Compiling'

# 3. interface change that does not compile: library unchanged
reset; D=$(sb t3); sed "$STMT; s/:= rfl/:= BROKEN/" lean/Paper/A.lean > "$D/Paper/A.lean"
OUT=$("$T/submit.sh" g1 "$D" Paper/A.lean 2>&1); rc=$?
check "statement change that fails to compile is put back" 1 $rc 'cmp -s lean/Paper/A.lean "$W/A.before"'

# 3b. proof-only change that does not compile: lands (existing design: the global build catches it)
reset; D=$(sb t3b); sed "s/:= rfl/:= BROKEN/" lean/Paper/A.lean > "$D/Paper/A.lean"
OUT=$("$T/submit.sh" g1 "$D" Paper/A.lean 2>&1); rc=$?
check "[existing design] broken proof-only change lands uncompiled" 0 $rc 'grep -q BROKEN lean/Paper/A.lean'

# 4. removing a declaration another module uses: refused by the check, put back
reset; D=$(sb t4); grep -v fooBarThm lean/Paper/A.lean > "$D/Paper/A.lean"
OUT=$("$T/submit.sh" g1 "$D" Paper/A.lean 2>&1); rc=$?
check "removal of a used declaration is refused" 3 $rc 'cmp -s lean/Paper/A.lean "$W/A.before"'

# 5. a set: rename in A, adapt B, both land together
reset; D=$(sb t5); sed 's/fooBarThm/fooBarThmRenamed/' lean/Paper/A.lean > "$D/Paper/A.lean"; sed 's/fooBarThm/fooBarThmRenamed/' lean/Paper/B.lean > "$D/Paper/B.lean"
OUT=$("$T/submit.sh" g1 "$D" Paper/A.lean Paper/B.lean 2>&1); rc=$?
check "set lands together" 0 $rc 'grep -q fooBarThmRenamed lean/Paper/A.lean && grep -q fooBarThmRenamed lean/Paper/B.lean'

# 6. a set where the importing file does not compile: every file put back
reset; D=$(sb t6); sed "$STMT" lean/Paper/A.lean > "$D/Paper/A.lean"; sed 's/fooBarThm$/BROKEN/' lean/Paper/B.lean > "$D/Paper/B.lean"
OUT=$("$T/submit.sh" g1 "$D" Paper/A.lean Paper/B.lean 2>&1); rc=$?
check "failed set is put back" 1 $rc 'cmp -s lean/Paper/A.lean "$W/A.before" && cmp -s lean/Paper/B.lean "$W/B.before"'

# 7. a new module
reset; D=$(sb t7); printf 'import Paper.A\n\ntheorem brandNewThm : True := trivial\n' > "$D/Paper/C.lean"
OUT=$("$T/submit.sh" g1 "$D" Paper/C.lean 2>&1); rc=$?
check "new module lands" 0 $rc '[ -f lean/Paper/C.lean ]'

# 7b. a sandbox outside the group's directory is refused
reset; d="$P/lean/.sandbox/other/t7b/lean"; mkdir -p "$d/Paper"; cp lean/Paper/A.lean "$d/Paper/A.lean"
OUT=$("$T/submit.sh" g1 "$d" Paper/A.lean 2>&1); rc=$?
check "sandbox of another group is refused" 2 $rc 'true'

# 8. landing records: every landing above is either requested (waiting for a build) or aborted
OUT=$(python3 "$T/landing.py" status 2>&1); rc=$?
check "landing.py status runs" 0 $rc 'true'
echo "--- landing status"; echo "$OUT" | head -12
echo "passed $pass, failed $fail"; [ $fail = 0 ]
