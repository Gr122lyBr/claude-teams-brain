#!/usr/bin/env bash
# claude-brain: SubagentStart hook
#
# Fires when a teammate is spawned. Reads agent_type from the event
# (the correct field per Claude Code docs), queries the brain for
# relevant role memory, and outputs it in the required hookSpecificOutput
# format so Claude Code injects it directly into the teammate's context.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="${SCRIPT_DIR}/brain_engine.py"
INPUT=$(cat)

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# agent_type is the correct SubagentStart input field (not agent_name)
AGENT_TYPE=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print((d.get('agent_type', '') or 'general').lower().strip())
" 2>/dev/null || echo "general")

[ -z "$AGENT_TYPE" ] && AGENT_TYPE="general"

# Query brain for role-relevant memory
CONTEXT=$(python3 "$ENGINE" query-role "$AGENT_TYPE" "$PROJECT_DIR" 2>/dev/null \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('additionalContext',''))" \
  2>/dev/null || echo "")

# Output in the required hookSpecificOutput format.
# additionalContext inside hookSpecificOutput is injected directly into
# the teammate's context (not shown in the transcript as noisy output).
if [ -n "$CONTEXT" ]; then
  python3 -c "
import json, sys
ctx = sys.argv[1]
print(json.dumps({
    'hookSpecificOutput': {
        'hookEventName': 'SubagentStart',
        'additionalContext': ctx
    }
}))
" "$CONTEXT"
fi

exit 0
