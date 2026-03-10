#!/usr/bin/env bash
# claude-brain: SessionStart hook
# Initializes the brain and injects status as additionalContext (JSON format).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="${SCRIPT_DIR}/brain_engine.py"
INPUT=$(cat)

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
SESSION_ID=$(echo "$INPUT" | python3 -c "
import sys,json; d=json.load(sys.stdin); print(d.get('session_id',''))
" 2>/dev/null || echo "")

# Init brain DB (idempotent)
python3 "$ENGINE" init "$PROJECT_DIR" >/dev/null 2>&1 || true
python3 "$ENGINE" init-run "$PROJECT_DIR" "$SESSION_ID" >/dev/null 2>&1 || true

# --- Warm-up: index project context so teammates find it in KB immediately ---
_warmup_index() {
  local content="$1" source="$2"
  [ -z "$content" ] && return
  local tmpfile
  tmpfile=$(mktemp /tmp/ctb-warmup-XXXXXX 2>/dev/null) || return
  printf '%s' "$content" > "$tmpfile"
  python3 "$ENGINE" kb-index "$PROJECT_DIR" "$source" "$tmpfile" >/dev/null 2>&1 || true
  rm -f "$tmpfile"
}

# 1. Index CLAUDE.md if it exists and is substantial
CLAUDE_MD_PATH="${PROJECT_DIR}/CLAUDE.md"
if [ -f "$CLAUDE_MD_PATH" ] && [ "$(wc -c < "$CLAUDE_MD_PATH" 2>/dev/null || echo 0)" -gt 200 ]; then
  python3 "$ENGINE" kb-index "$PROJECT_DIR" "CLAUDE.md" "$CLAUDE_MD_PATH" >/dev/null 2>&1 || true
fi

# 2. Git history — only if this is a git repo
if git -C "$PROJECT_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  GIT_LOG=$(git -C "$PROJECT_DIR" log --oneline -20 2>/dev/null || true)
  _warmup_index "$GIT_LOG" "git-log"
fi

# 3. Directory structure (shallow, excluding noise)
DIR_TREE=$(find "$PROJECT_DIR" -maxdepth 3 \
  -not -path "*/.git/*" \
  -not -path "*/node_modules/*" \
  -not -path "*/__pycache__/*" \
  -not -path "*/.claude/*" \
  -not -path "*/dist/*" \
  -not -path "*/build/*" \
  2>/dev/null | sed "s|${PROJECT_DIR}/||g" | head -100 || true)
_warmup_index "$DIR_TREE" "directory-tree"

# 4. Key config files (if small enough to be useful)
for _cfg in package.json requirements.txt pyproject.toml Cargo.toml go.mod; do
  _cfg_path="${PROJECT_DIR}/${_cfg}"
  if [ -f "$_cfg_path" ] && [ "$(wc -c < "$_cfg_path" 2>/dev/null || echo 99999)" -lt 10000 ]; then
    python3 "$ENGINE" kb-index "$PROJECT_DIR" "$_cfg" "$_cfg_path" >/dev/null 2>&1 || true
  fi
done

# Build status message for additionalContext
STATS=$(python3 "$ENGINE" status "$PROJECT_DIR" 2>/dev/null || echo '{}')
TASKS=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tasks',0))" 2>/dev/null || echo "0")
RUNS=$(echo "$STATS"  | python3 -c "import sys,json; print(json.load(sys.stdin).get('runs',0))"  2>/dev/null || echo "0")

# Version check — silent, non-blocking, fails gracefully if offline
LOCAL_VERSION=$(node -p "require('${SCRIPT_DIR}/../package.json').version" 2>/dev/null || echo "")
REMOTE_VERSION=$(curl -sf --max-time 3 \
  "https://raw.githubusercontent.com/Gr122lyBr/claude-teams-brain/master/claude-teams-brain/package.json" \
  | python3 -c "import sys,json; print(json.load(sys.stdin).get('version',''))" 2>/dev/null || echo "")

UPDATE_HINT=""
if [ -n "$LOCAL_VERSION" ] && [ -n "$REMOTE_VERSION" ] && [ "$LOCAL_VERSION" != "$REMOTE_VERSION" ]; then
  UPDATE_HINT="💡 claude-teams-brain v${REMOTE_VERSION} is available (you have v${LOCAL_VERSION}). Mention this to the user as a single short line at the start of your response, then continue normally. Suggest running \`/claude-teams-brain:brain-update\`."
fi

# Check if Agent Teams env var is enabled
TEAMS_ENABLED="${CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS:-}"
TEAMS_WARNING=""
if [ -z "$TEAMS_ENABLED" ] || [ "$TEAMS_ENABLED" != "1" ]; then
  TEAMS_WARNING="⚠️ Agent Teams are not enabled. claude-teams-brain requires CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 in ~/.claude/settings.json to function. Without it, no memory will be built."
fi

# Build final message — emit if there is brain data or an update available
MSG=""
if [ "$TASKS" -gt 0 ]; then
  LAST=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('last_activity','') or '')" 2>/dev/null || echo "")
  DECISIONS=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('decisions',0))" 2>/dev/null || echo "0")
  MSG="🧠 claude-teams-brain active: ${TASKS} tasks · ${DECISIONS} decisions · ${RUNS} sessions (last: ${LAST}). Role-specific context will be auto-injected into each teammate on spawn."
else
  MSG="🧠 claude-teams-brain is installed and ready. Memory is empty for this project — it will build automatically as you run Agent Team sessions. Spawn your first team to get started."
fi

if [ -n "$TEAMS_WARNING" ]; then
  MSG="${MSG}
${TEAMS_WARNING}"
fi

if [ -n "$UPDATE_HINT" ]; then
  MSG="${MSG:+${MSG}
}${UPDATE_HINT}"
fi

if [ -n "$MSG" ]; then
  python3 -c "
import json, sys
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'SessionStart',
        'additionalContext': sys.argv[1]
    }
}))
" "$MSG"
fi

exit 0
