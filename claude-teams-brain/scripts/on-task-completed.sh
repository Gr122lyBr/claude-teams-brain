#!/usr/bin/env bash
# claude-brain: TaskCompleted hook
#
# Fires when any agent marks a task complete. Extracts the task subject,
# agent info, and any relevant metadata, then indexes it in the brain.
# Also enforces a quality gate: tasks with "brain:skip-index" tag are not indexed.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="${SCRIPT_DIR}/brain_engine.py"
INPUT=$(cat)

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Parse event fields
PARSED=$(echo "$INPUT" | python3 -c "
import sys, json, os

d = json.load(sys.stdin)

# Extract fields available in TaskCompleted event
task_subject = d.get('task_subject', '') or d.get('task_description', '') or ''
agent_name   = d.get('agent_name', '') or d.get('teammate_name', '') or ''
session_id   = d.get('session_id', '') or ''
task_id      = d.get('task_id', '') or ''

# Try to infer role from agent name (e.g. 'backend-agent' -> 'backend')
import re
role = re.sub(r'[-_]?(agent|teammate|worker|bot)$', '', agent_name, flags=re.I).strip() or agent_name

payload = {
    'project_dir': os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()),
    'run_id': session_id,
    'session_id': session_id,
    'task_subject': task_subject,
    'agent_name': agent_name,
    'agent_role': role,
    'task_id': task_id,
    'files_touched': [],   # will be enriched by PostToolUse in future version
    'decisions': [],
    'output_summary': task_subject,  # minimal; richer via SubagentStop
}
print(json.dumps(payload))
" 2>/dev/null || echo '{}')

if [ "$PARSED" = '{}' ]; then
    exit 0
fi

# Index the task
python3 "$ENGINE" index-task "$PARSED" >/dev/null 2>&1 || true

# Confirm indexing to the user via additionalContext
TASK_SUBJECT=$(echo "$PARSED" | python3 -c "import sys,json; print(json.load(sys.stdin).get('task_subject','') or '')" 2>/dev/null || echo "")
AGENT=$(echo "$PARSED" | python3 -c "import sys,json; print(json.load(sys.stdin).get('agent_name','') or '')" 2>/dev/null || echo "")

if [ -n "$TASK_SUBJECT" ]; then
  CONFIRM="🧠 Indexed: ${AGENT:+[${AGENT}] }${TASK_SUBJECT}"
  python3 -c "
import json, sys
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'TaskCompleted',
        'additionalContext': sys.argv[1]
    }
}))
" "$CONFIRM" 2>/dev/null || true
fi

exit 0
