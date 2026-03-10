---
name: brain-search
description: |
  Search the brain knowledge base directly for any query.
  Use: /brain-search <query>
user_invocable: true
---

# brain-search

Search everything the brain has indexed — tasks, decisions, files, and session KB — for a query.

## Instructions

The user provides a search query as an argument.

Run:
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py kb-search "$CLAUDE_PROJECT_DIR" "$ARGS" 5
```

Display results clearly with titles and snippets.
If nothing is found, say so and suggest using `/brain-remember` to add facts or running an Agent Team session to build memory.
