# brain-replay

Time-travel through any past Agent Team session — see who did what, what decisions were made, and what files were touched, in chronological order.

## Trigger

This skill activates when the user runs `/brain-replay`, `/brain-replay <run-id>`, or `/claude-teams-brain:brain-replay`.

## Workflow

### Step 1 — Replay the session

If the user provided a run-id argument, or no argument at all, go straight to replay:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py" replay-run "<run_id_or_latest>" "${CLAUDE_PROJECT_DIR}"
```

- No argument or `latest` or `last` → replays the most recent session automatically.
- Partial run IDs work too — `3de2ae` will match `3de2ae4f...`.

**Only if** the user explicitly asks to pick a session, list available sessions:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py" list-runs "${CLAUDE_PROJECT_DIR}"
```

Present sessions to the user:
```
Recent sessions:
  3de2ae4f  2026-03-10 14:22  3 tasks  2 agents  (backend, frontend)
  8b55bbf1  2026-03-09 11:05  5 tasks  3 agents  (backend, database, tests)
```

Then ask which session to replay and run the `replay-run` command with their choice.

### Step 2 — Render the narrative

Parse the JSON response:
- `status` — "ok" or "not_found"
- `run_id` — the full resolved run ID
- `narrative` — the full Markdown narrative to render

Output the `narrative` field directly as formatted Markdown. It contains:

- **Header**: run ID, start/end time, team members, task count
- **Timeline**: numbered list of tasks with agent, timestamp, files touched, decisions, summary
- **All Decisions**: every architectural decision made during the session
- **Files Touched**: all files modified with the agents that touched them
- **Session Summary**: compressed end-of-session summary

### Step 3 — Offer follow-up actions

After showing the replay, offer:
> "**What would you like to do next?**
> - `/brain-export` — export all accumulated knowledge as CONVENTIONS.md
> - `/brain-search <query>` — search for something specific from this session
> - `/brain-query <role>` — preview what a new teammate would receive"

## Notes

- Replay works for both Agent Teams sessions and solo sessions
- The more sessions you have, the more useful replay becomes for understanding project history
- `${CLAUDE_PLUGIN_ROOT}` and `${CLAUDE_PROJECT_DIR}` are set by Claude Code's hook environment

**Important**: Only use the exact commands shown above (`replay-run` and `list-runs`). Do not invent or guess other command names.
