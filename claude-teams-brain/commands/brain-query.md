---
name: brain-query
description: Query the claude-teams-brain for context about a specific role or topic
---

Query the claude-teams-brain memory index for context relevant to a role or topic.

Usage: `/brain-query <role-or-topic>`

Examples:
- `/brain-query backend`
- `/brain-query authentication`
- `/brain-query database`

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py query-role "$ARGS" "$CLAUDE_PROJECT_DIR"`

Display the returned context in a readable format. If no relevant memory is found, say so clearly.
This is the same context that would be auto-injected into a teammate with that role name.
