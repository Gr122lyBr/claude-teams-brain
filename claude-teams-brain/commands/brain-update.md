---
name: brain-update
description: Update claude-teams-brain to the latest version from GitHub
---

Update claude-teams-brain by pulling the latest version from GitHub and syncing it to the plugin cache.

Run:
```
bash ${CLAUDE_PLUGIN_ROOT}/scripts/update.sh
```

After the script completes, display the results as markdown:
```
## claude-teams-brain update
- [x] Pulled latest from GitHub
- [x] Synced to plugin cache
- [x] Version: <version>
- [x] Changes: <summary of changed files or "already up to date">
```

Use `[x]` for success, `[ ]` for failed steps.
If hooks or settings changed, tell the user to restart Claude Code to apply them.
