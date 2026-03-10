---
name: brain-remember
description: |
  Store a persistent rule or convention that will be injected into all future teammates.
  Use: /brain-remember <text>
user_invocable: true
---

# brain-remember

Store a fact, rule, or convention in the brain. It will be automatically injected into every future teammate under "Project Rules & Conventions" — regardless of their role.

## Instructions

The user provides the memory text as an argument.

Run:
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py remember "$ARGS" "$CLAUDE_PROJECT_DIR"
```

Confirm success and echo back the stored memory.
Tell the user it will appear in every new teammate's context automatically.
Mention `/brain-forget` to remove it if needed.
