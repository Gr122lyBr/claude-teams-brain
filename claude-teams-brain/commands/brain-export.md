---
name: brain-export
description: Export accumulated brain knowledge as a CONVENTIONS.md file in your project
---

Export all accumulated brain knowledge — manual rules, architectural decisions, key files, and agent roles — into a `CONVENTIONS.md` file written to the project root.

Run:
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py export-conventions "$CLAUDE_PROJECT_DIR"
```

Take the `content` field from the JSON output and write it to `CONVENTIONS.md` in `$CLAUDE_PROJECT_DIR`.

After writing the file:
- Confirm how many rules, decisions, and files were exported
- Tell the user they can commit `CONVENTIONS.md` to share accumulated team knowledge with humans and future AI sessions alike
- Suggest running `/brain-remember` to add any missing rules before exporting
