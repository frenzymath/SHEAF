#!/bin/bash
# Report the state of every tmux session of this project (for the launcher).
# Usage: tools/session_health.sh
# A session belongs to the project when it was started in the project directory (`tmux new-session -c <project directory>`).
# One line per session: <session> <STATE> [detail]
#   OK        the screen changed since the last check
#   QUIET m   no change for m minutes (15 <= m < SHEAF_STUCK_MIN)
#   STUCK m   no change for at least SHEAF_STUCK_MIN minutes (default 60): read the screen, then restart the session
#   WAITING   the screen shows a question or a confirmation prompt: read it and answer it as the contract says
#   LIMIT     the screen shows a usage or rate limit, or an API error: record it and wait
#   DEAD      the session's process has exited: restart it
# Restart with the command recorded in coord/STATE.md; stop a session by its name or PID, never by a pattern.
set -u
source "$(dirname "$0")/sheaf_env.sh"
STUCK=${SHEAF_STUCK_MIN:-60}; D="$SHEAF_ROOT/local/health"; mkdir -p "$D"; now=$(date +%s)
for s in $(tmux list-sessions -F '#S' 2>/dev/null); do
  [ "$(realpath "$(tmux display -p -t "$s" '#{session_path}' 2>/dev/null)" 2>/dev/null)" = "$SHEAF_ROOT" ] || continue
  if [ "$(tmux list-panes -t "$s" -F '#{pane_dead}' | head -1)" = 1 ]; then echo "$s DEAD"; continue; fi
  screen=$(tmux capture-pane -t "$s" -p -S -60)
  h=$(printf '%s' "$screen" | md5sum | cut -c1-16); since=$now; old=""
  [ -f "$D/$s" ] && read -r old since < "$D/$s"
  [ "$h" != "$old" ] && since=$now
  printf '%s %s\n' "$h" "$since" > "$D/$s"
  quiet=$(( (now - since) / 60 )); tail=$(printf '%s' "$screen" | tail -25)
  if printf '%s' "$tail" | grep -qiE 'usage limit|rate limit|API Error|overloaded|credit balance'; then
    echo "$s LIMIT $(printf '%s' "$tail" | grep -m1 -oiE '(usage limit|rate limit|API Error|overloaded|credit balance)[^.]*')"
  elif printf '%s' "$tail" | grep -qE 'Do you want to|Press Enter to continue|\(y/n\)|❯ 1\.'; then echo "$s WAITING"
  elif [ $quiet -ge "$STUCK" ]; then echo "$s STUCK $quiet"
  elif [ $quiet -ge 15 ]; then echo "$s QUIET $quiet"
  else echo "$s OK"; fi
done
