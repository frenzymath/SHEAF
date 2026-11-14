#!/bin/bash
# Submit command of the first layout of skills/compiling/SKILL.md, one worktree per worker: the delivery's Lean files
# become one pull request to the main repository (tools/prs.py), and the command waits until the managing agent has
# merged it or sent it back. A sketch, written quickly: change it to fit the project, as long as the skill's rules hold.
# Usage: tools/submit_pr.sh <group> <sandbox lean directory> <file under lean/>...
# Exit 0: merged into the main repository. 1: sent back, with the managing agent's reason.
# Each submission waits for its batch, so accept_slots in coord/dispatch.json must be at least the number of
# pull requests that may wait at once, about slots; a waiting acceptance costs nothing.
set -u
T=$(cd "$(dirname "$0")" && pwd)
G=$1; DIR=$2; shift 2
ID=$(python3 "$T/prs.py" open "$G" "$DIR" "$@") || exit 9
echo "pull request $ID"
exec python3 "$T/prs.py" wait "$ID"
