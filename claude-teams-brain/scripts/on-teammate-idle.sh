#!/usr/bin/env bash
# claude-brain: TeammateIdle hook
#
# Fires when a teammate runs out of tasks and goes idle.
# Currently: silent pass-through (allows idle).
# The brain already captured their work via SubagentStop/TaskCompleted.
#
# Optional: set CLAUDE_BRAIN_AUTO_CHECKPOINT=1 to log idle events.

set -euo pipefail

INPUT=$(cat)

if [ "${CLAUDE_BRAIN_AUTO_CHECKPOINT:-0}" = "1" ]; then
    AGENT=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('agent_name', '') or d.get('teammate_name', '') or 'unknown')
" 2>/dev/null || echo "unknown")
    echo "🧠 claude-brain: Teammate '$AGENT' went idle — work has been indexed." >&2
fi

# Exit 0 = allow idle normally
exit 0
