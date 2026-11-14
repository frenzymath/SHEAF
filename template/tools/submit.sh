#!/bin/bash
# The default submit command of tools/accept.py: puts a delivery's Lean files into the library.
# Usage: tools/submit.sh <group> <sandbox lean directory> <file under lean/>...
# One file lands with tools/land.sh, several as one set with tools/land_set.sh. Exit 0: the files are in the library.
# How a delivery is verified and enters the library is not settled by the three-stage code: replace this command
# (submit_cmd in coord/dispatch.json) to change it.
set -u
T=$(cd "$(dirname "$0")" && pwd)
G=$1; DIR=$2; shift 2
export SHEAF_GROUP=$G
if [ $# -eq 1 ]; then
  exec "$T/land.sh" "$DIR/$1" "$(dirname "$T")/lean/$1"
else
  exec "$T/land_set.sh" "$DIR"
fi
