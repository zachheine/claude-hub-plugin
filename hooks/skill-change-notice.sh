#!/bin/bash
# UserPromptSubmit hook: tell a session, once, when an installed skill it may be
# running has changed on disk since this session last saw it.
#
# Runs by the harness on every prompt in every session. Prints nothing when
# nothing changed, so it costs no tokens at rest. When a watched skill's files
# differ from the hash this session last recorded, it prints one line, which the
# harness adds to the session's context. That replaces broadcasting skill
# updates by message, which is capped, can be refused by a blocked session, and
# misses sessions that are not open.
#
# State: ~/.claude/hooks/state/skills.<session_id> holds "name hash" lines.
# First prompt of a session records and stays silent.

SKILLS_DIR="$HOME/.claude/skills"
WATCH="hub dispatch changelog"
STATE_DIR="$HOME/.claude/hooks/state"

input="$(cat)"
sid="$(printf '%s' "$input" | /usr/bin/python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("session_id",""))
except Exception: print("")' 2>/dev/null)"
[ -z "$sid" ] && sid="${CLAUDE_CODE_SESSION_ID:-unknown}"
state="$STATE_DIR/skills.$sid"

current=""
for name in $WATCH; do
  dir="$SKILLS_DIR/$name"
  [ -d "$dir" ] || continue
  h="$(find "$dir" -type f -print0 | sort -z | xargs -0 shasum -a 256 2>/dev/null | shasum -a 256 | cut -c1-12)"
  current="$current$name $h"$'\n'
done

if [ ! -f "$state" ]; then
  printf '%s' "$current" > "$state"
  exit 0
fi

changed=""
while read -r name h; do
  [ -z "$name" ] && continue
  old="$(grep "^$name " "$state" | cut -d' ' -f2)"
  if [ -n "$old" ] && [ "$old" != "$h" ]; then changed="$changed $name"; fi
done <<< "$current"

printf '%s' "$current" > "$state"

if [ -n "$changed" ]; then
  version=""
  pj="$HOME/Developer/claude/claude-hub-plugin/.claude-plugin/plugin.json"
  [ -f "$pj" ] && version="$(/usr/bin/python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("version",""))' "$pj" 2>/dev/null)"
  echo "Installed skill(s) changed on disk since this session last loaded them:${changed}${version:+ (plugin $version)}. If this session runs one of them (/hub, /dispatch, /changelog), re-invoke it to reload before acting on anything else. Otherwise ignore this line."
fi
exit 0
