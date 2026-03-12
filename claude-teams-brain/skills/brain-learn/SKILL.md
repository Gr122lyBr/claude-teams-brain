---
name: brain-learn
description: |
  Auto-learn project conventions from git history — zero manual setup.
  Trigger: /brain-learn
user_invocable: true
---

# brain-learn

Scan the repo's git history and automatically extract conventions, architecture signals, file coupling patterns, and code hotspots. The brain teaches itself from your repo — no manual `/brain-remember` needed.

## Instructions

Run:
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py learn "$CLAUDE_PROJECT_DIR"
```

Parse the JSON response which contains:
- `status` — "ok" or "error"
- `commits_analyzed` — number of commits scanned (up to 200)
- `conventions_found` — total conventions detected
- `conventions_added` — new conventions stored (excludes duplicates)
- `conventions_skipped` — conventions already in the brain
- `file_couplings` — number of file coupling patterns found
- `hotspots` — number of hotspot entries (files + directories)
- `conventions` — list of convention strings that were added
- `message` — human-readable summary

Display results grouped by category:

```
## Learned from Git History

**Commits analyzed**: 187

### Conventions Added (6 new, 2 already known)
- Convention: commit messages use Conventional Commits — common scopes: api, auth, db
- Convention: branches use prefix naming (feature/, fix/, chore/)
- Architecture: primary stack is TypeScript (Node.js)
- Architecture: CI/CD uses GitHub Actions
- Architecture: uses Docker for containerization
- Convention: tests use *.test.ts naming

### Also Indexed
- 12 file coupling patterns (searchable via `/brain-search coupling`)
- 23 code hotspots (searchable via `/brain-search hotspots`)
```

After displaying results, suggest:
> **Next steps:**
> - `/brain-search coupling` — see which files change together
> - `/brain-search hotspots` — see the most active files
> - `/brain-status` — verify the brain state
> - `/brain-forget <text>` — remove any convention that doesn't apply

The command is idempotent — running it again only adds net-new findings.

**Important**: Only use the exact command shown above. Do not invent or guess other command names.
