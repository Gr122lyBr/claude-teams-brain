#!/usr/bin/env bash
# claude-brain: SubagentStop hook
# Fires when a teammate finishes. Reads agent_type (correct field per docs),
# parses agent_transcript_path for files touched + decisions, indexes it all.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="${SCRIPT_DIR}/brain_engine.py"
INPUT=$(cat)

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

PARSED=$(echo "$INPUT" | python3 -c "
import sys, json, os, re

d = json.load(sys.stdin)

# agent_type is the correct SubagentStop field (not agent_name)
agent_name      = d.get('agent_type', '') or 'unknown'
session_id      = d.get('session_id', '') or ''
# agent_transcript_path is the subagent's own transcript (not transcript_path)
transcript_path = d.get('agent_transcript_path', '') or ''
last_message    = d.get('last_assistant_message', '') or ''

files_touched = []
decisions     = []
output_summary = ''

if transcript_path and os.path.exists(transcript_path):
    try:
        with open(transcript_path) as f:
            entries = [json.loads(line) for line in f if line.strip()]

        for entry in entries:
            msg = entry.get('message', {})
            content = msg.get('content', [])
            if not isinstance(content, list):
                continue
            for block in content:
                if not isinstance(block, dict):
                    continue
                # Capture file writes/edits
                if block.get('type') == 'tool_use' and block.get('name') in ('Write', 'Edit', 'MultiEdit', 'Create'):
                    fp = (block.get('input', {}).get('file_path', '')
                          or block.get('input', {}).get('path', ''))
                    if fp and fp not in files_touched:
                        files_touched.append(fp)
                # Capture decisions from text
                if block.get('type') == 'text':
                    for line in block.get('text', '').split('\n'):
                        lc = line.lower()
                        if any(kw in lc for kw in ['decided to', 'chose to', 'will use', 'approach:', 'decision:', 'rationale:']):
                            clean = line.strip()[:200]
                            if clean and clean not in decisions:
                                decisions.append(clean)

        # Last assistant message as summary
        if last_message:
            output_summary = last_message[:500]
        else:
            for entry in reversed(entries):
                msg = entry.get('message', {})
                if msg.get('role') == 'assistant':
                    for block in reversed(msg.get('content', []) if isinstance(msg.get('content'), list) else []):
                        if isinstance(block, dict) and block.get('type') == 'text':
                            output_summary = block['text'][:500]
                            break
                    if output_summary:
                        break
    except Exception:
        pass

if not output_summary and last_message:
    output_summary = last_message[:500]

role = re.sub(r'[-_]?(agent|teammate|worker|bot)$', '', agent_name, flags=re.I).strip() or agent_name

payload = {
    'project_dir': os.environ.get('CLAUDE_PROJECT_DIR', os.getcwd()),
    'run_id': session_id,
    'session_id': session_id,
    'task_subject': f'Work by {agent_name}',
    'agent_name': agent_name,
    'agent_role': role,
    'files_touched': files_touched[:50],
    'decisions': decisions[:20],
    'output_summary': output_summary,
}
print(json.dumps(payload))
" 2>/dev/null || echo '{}')

if [ "$PARSED" != '{}' ]; then
    python3 "$ENGINE" index-task "$PARSED" >/dev/null 2>&1 || true
fi

exit 0
