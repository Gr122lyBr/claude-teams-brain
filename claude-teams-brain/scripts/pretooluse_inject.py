#!/usr/bin/env python3
"""PreToolUse hook helper: injects MCP routing instructions and team memories into Task subagent prompts."""
import sys
import json
import subprocess
import re
import os


ROUTING_BLOCK = """
---
CONTEXT WINDOW PROTECTION — USE CLAUDE-TEAMS-BRAIN MCP TOOLS

STEP 1 — GATHER: mcp__claude-teams-brain__batch_execute(commands, queries)
  commands: [{"label": "Name", "command": "shell cmd"}, ...]
  queries: ["query1", "query2"] — cover everything you need in one call.
  Runs all commands, indexes output, returns search results. ONE call, no follow-ups.

STEP 2 — FOLLOW-UP: mcp__claude-teams-brain__search(queries: ["q1", "q2"])
  Pass ALL follow-up questions as array. ONE call.

OTHER TOOLS:
  mcp__claude-teams-brain__execute(language, code, intent?) — run code in sandbox
  mcp__claude-teams-brain__index(content, source) — save findings for team
  mcp__claude-teams-brain__stats() — check context savings

RULES:
- Avoid raw Bash for large output — use batch_execute instead
- Keep final response under 500 words
- Write artifacts (configs, code) to FILES, not inline text
- Index detailed findings: mcp__claude-teams-brain__index(content, source)
---
"""


def main():
    project_dir = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    engine = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "brain_engine.py")

    try:
        input_data = json.loads(sys.stdin.read())
    except Exception:
        print("{}")
        return

    tool_name = input_data.get("tool_name", "")
    if tool_name != "Task":
        print("{}")
        return

    tool_input = input_data.get("tool_input", {})
    subagent_type = tool_input.get("subagent_type", "")
    original_prompt = tool_input.get("prompt", "")

    # Clean agent type for role lookup
    role = re.sub(r"-(agent|teammate|worker|bot)$", "", subagent_type.lower()).strip()
    if not role:
        role = "general"

    # Query brain for this role's memory (query-role <role> [<project_dir>])
    memory = ""
    try:
        result = subprocess.run(
            [sys.executable, engine, "query-role", role, project_dir],
            capture_output=True, text=True, timeout=6
        )
        raw = result.stdout.strip()
        try:
            data = json.loads(raw)
            memory = data.get("additionalContext", "")
        except Exception:
            memory = raw
    except Exception:
        pass

    # Build the injection: always include routing block, optionally add memory
    injection = ROUTING_BLOCK

    if memory and "No previous work found" not in memory:
        memory_block = (
            "\n---\n"
            "TEAM MEMORY (claude-teams-brain)\n"
            "Previous work by agents with this role:\n\n"
            f"{memory}\n"
            "---\n"
        )
        injection += memory_block

    updated_input = dict(tool_input)
    updated_input["prompt"] = original_prompt + injection

    # Upgrade Bash subagents to general-purpose so they have MCP access
    if subagent_type == "Bash":
        updated_input["subagent_type"] = "general-purpose"

    output = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "updatedInput": updated_input
        }
    }
    print(json.dumps(output))


if __name__ == "__main__":
    main()
