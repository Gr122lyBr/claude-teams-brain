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

# Build status message for additionalContext
STATS=$(python3 "$ENGINE" status "$PROJECT_DIR" 2>/dev/null || echo '{}')
TASKS=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('tasks',0))" 2>/dev/null || echo "0")
RUNS=$(echo "$STATS"  | python3 -c "import sys,json; print(json.load(sys.stdin).get('runs',0))"  2>/dev/null || echo "0")

if [ "$TASKS" -gt 0 ]; then
  LAST=$(echo "$STATS" | python3 -c "import sys,json; print(json.load(sys.stdin).get('last_activity','') or '')" 2>/dev/null || echo "")
  MSG="🧠 claude-brain active: ${TASKS} tasks indexed across ${RUNS} sessions (last: ${LAST}). Role-specific context will be auto-injected into each teammate on spawn."

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
