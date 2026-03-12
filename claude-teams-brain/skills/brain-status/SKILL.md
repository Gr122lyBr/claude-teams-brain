---
name: brain-status
description: |
  Quick overview of brain memory — use /brain-stats for detailed breakdown with KB and per-role info
user_invocable: true
---

# brain-status

Quick overview of brain memory for this project. For a full detailed breakdown (including session KB and per-role stats), suggest `/brain-stats` instead.

## Instructions

Run these two commands:
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py status "$CLAUDE_PROJECT_DIR"
```
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py list-tasks "$CLAUDE_PROJECT_DIR" 3
```

Display the status results in a clear, human-readable format:
- Total tasks indexed
- Total sessions recorded
- Decisions logged
- Files in the index
- Distinct agents seen
- Last activity timestamp

If the brain has data, also display the 3 most recent tasks from the `list-tasks` output.
If the brain is empty, tell the user memory will start building automatically once they run an Agent Team session.

**Important**: Only use the exact commands shown above. Do not invent or guess other command names.
