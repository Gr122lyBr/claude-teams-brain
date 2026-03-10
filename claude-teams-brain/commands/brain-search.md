---
name: brain-search
description: Search the brain knowledge base directly
---

Search everything the brain has indexed — tasks, decisions, files, and session KB — for a query.

Usage: `/brain-search <query>`

Run:
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py kb-search "$CLAUDE_PROJECT_DIR" "$ARGS" 5
```

Display the results clearly. If nothing is found, say so and remind the user that memory builds automatically after Agent Team sessions — or they can use `/brain-remember` to add facts manually.
