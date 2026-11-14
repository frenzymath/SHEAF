#!/bin/bash
# The submit command of SHEAF's first application: puts a delivery's Lean files into one library, verified afterwards
# by the global build (tools/build.py). It is not the default: a change to proofs alone enters without a compile, which
# skills/compiling/SKILL.md §4 does not allow; change that before using it.
# Usage: tools/submit.sh <group> <sandbox lean directory> <file under lean/>...
# One file lands with tools/land.sh, several as one set with tools/land_set.sh. Exit 0: the files are in the library.
set -u
T=$(cd "$(dirname "$0")" && pwd)
G=$1; DIR=$2; shift 2
export SHEAF_GROUP=$G
if [ $# -eq 1 ]; then
  exec "$T/land.sh" "$DIR/$1" "$(dirname "$T")/lean/$1"
else
  exec "$T/land_set.sh" "$DIR"
fi
