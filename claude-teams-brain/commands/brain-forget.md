---
name: brain-forget
description: Remove a manually stored memory from the brain
---

Remove a manual memory previously stored with `/brain-remember`.

Usage: `/brain-forget <text>`

Partial matches are supported — any memory containing the provided text will be removed.

Examples:
- `/brain-forget UUID v7`
- `/brain-forget legacy directory`

Run:
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py forget "$ARGS" "$CLAUDE_PROJECT_DIR"
```

Show which memories were removed. If no match is found, say so clearly and suggest using `/brain-status` to see what's stored.
