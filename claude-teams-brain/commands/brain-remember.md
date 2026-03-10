---
name: brain-remember
description: Store a persistent rule or convention that will be injected into all future teammates
---

Store a fact, rule, or convention in the brain. It will be automatically injected into every future teammate under "Project Rules & Conventions" — regardless of their role.

Usage: `/brain-remember <text>`

Examples:
- `/brain-remember always use UUID v7 for all new database tables`
- `/brain-remember never modify files in the legacy/ directory without explicit approval`
- `/brain-remember all API endpoints must include rate limiting`

Run:
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py remember "$ARGS" "$CLAUDE_PROJECT_DIR"
```

Confirm success and echo back the stored memory. Tell the user it will appear in every new teammate's context under "Project Rules & Conventions".

If the user wants to remove a memory later, they can use `/brain-forget`.
