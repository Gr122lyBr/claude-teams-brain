#!/usr/bin/env python3
"""
hook_runner.py — Cross-platform hook dispatcher for claude-teams-brain.

Replaces all bash hook scripts. Works on macOS, Linux, WSL2, and native
Windows without modification — requires only Python 3.8+ (already a dependency).

Usage:
  python3 hook_runner.py <event>

Events:
  session-start     SessionStart lifecycle hook
  session-end       SessionEnd lifecycle hook
  subagent-start    SubagentStart lifecycle hook
  subagent-stop     SubagentStop lifecycle hook
  task-completed    TaskCompleted lifecycle hook
  teammate-idle     TeammateIdle lifecycle hook
  pretooluse-task   PreToolUse (Task matcher) hook
"""

import sys
import os
import json
import re
import subprocess
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ENGINE = str(SCRIPT_DIR / "brain_engine.py")


# ── Helpers ────────────────────────────────────────────────────────────────────

def run_engine(*args, input_data=None):
    """Run brain_engine.py with the given args. Returns stdout string."""
    cmd = [sys.executable, ENGINE] + [str(a) for a in args]
    try:
        result = subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            text=True,
            timeout=30,
            env=os.environ.copy(),
        )
        return result.stdout.strip()
    except Exception:
        return ""


def emit_context(event_name, context):
    """Print the hookSpecificOutput JSON Claude Code expects."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": event_name,
            "additionalContext": context,
        }
    }))


def get_project_dir():
    return os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())


def read_input():
    try:
        return json.loads(sys.stdin.read())
    except Exception:
        return {}


def index_text(project_dir, source, content):
    """Write content to a temp file and index it into the KB."""
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(content)
            tmp = f.name
        run_engine("kb-index", project_dir, source, tmp)
        Path(tmp).unlink(missing_ok=True)
    except Exception:
        pass


def dir_tree(project_dir):
    """Pure-Python directory tree (cross-platform, no find/ls needed)."""
    exclude = {
        ".git", "node_modules", "__pycache__", ".claude",
        "dist", "build", ".venv", "venv", ".tox", "coverage",
    }
    lines = []
    root = Path(project_dir)

    def walk(path, depth=0):
        if depth > 3:
            return
        try:
            entries = sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name))
            for entry in entries:
                if entry.name in exclude or entry.name.startswith("."):
                    continue
                try:
                    rel = str(entry.relative_to(root))
                    lines.append(rel)
                    if entry.is_dir() and depth < 2 and len(lines) < 100:
                        walk(entry, depth + 1)
                except Exception:
                    pass
        except PermissionError:
            pass

    walk(root)
    return "\n".join(lines[:100])


def check_version():
    """Non-blocking version check. Returns update hint string or ''."""
    try:
        pkg = SCRIPT_DIR.parent / "package.json"
        local_version = json.loads(pkg.read_text(encoding="utf-8")).get("version", "")
        if not local_version:
            return ""
        import urllib.request
        url = (
            "https://raw.githubusercontent.com/Gr122lyBr/claude-teams-brain"
            "/master/claude-teams-brain/package.json"
        )
        with urllib.request.urlopen(url, timeout=3) as resp:
            remote_version = json.loads(resp.read()).get("version", "")
        if remote_version and remote_version != local_version:
            return (
                f"💡 claude-teams-brain v{remote_version} is available "
                f"(you have v{local_version}). "
                "Run `/claude-teams-brain:brain-update` to upgrade."
            )
    except Exception:
        pass
    return ""


def warmup(project_dir):
    """Index project context sources into the session KB."""
    # 1. CLAUDE.md
    claude_md = Path(project_dir) / "CLAUDE.md"
    if claude_md.exists() and claude_md.stat().st_size > 200:
        run_engine("kb-index", project_dir, "CLAUDE.md", str(claude_md))

    # 2. Git history
    try:
        result = subprocess.run(
            ["git", "-C", project_dir, "log", "--oneline", "-20"],
            capture_output=True, text=True, timeout=10,
        )
        if result.stdout.strip():
            index_text(project_dir, "git-log", result.stdout)
    except Exception:
        pass

    # 3. Directory tree (pure Python — works on all platforms)
    try:
        tree = dir_tree(project_dir)
        if tree:
            index_text(project_dir, "directory-tree", tree)
    except Exception:
        pass

    # 4. Key config files
    for cfg in [
        "package.json", "requirements.txt", "pyproject.toml",
        "Cargo.toml", "go.mod", "composer.json", "Gemfile",
    ]:
        cfg_path = Path(project_dir) / cfg
        if cfg_path.exists() and cfg_path.stat().st_size < 10000:
            run_engine("kb-index", project_dir, cfg, str(cfg_path))

    # 5. Auto-seed from existing convention files (zero-config onboarding)
    for conv_file in [".cursorrules", "AGENTS.md", "CONVENTIONS.md"]:
        conv_path = Path(project_dir) / conv_file
        if conv_path.exists() and conv_path.stat().st_size > 100:
            run_engine("kb-index", project_dir, conv_file, str(conv_path))


TOOL_GUIDANCE = """\
## Token-Efficient Tools (claude-teams-brain)
Prefer these MCP tools over direct Bash calls to minimise context usage:
- `batch_execute` — run multiple shell commands in a single call; all output is auto-indexed and searchable
- `execute` — run a single command with automatic output indexing
- `search` — query indexed output instead of re-running commands
- `index` — store any content in the session knowledge base for later retrieval
- `stats` — view token savings and call counts for this session

Always prefer `batch_execute` when issuing more than one shell command."""


# ── Hook handlers ──────────────────────────────────────────────────────────────

def hook_session_start(data):
    project_dir = get_project_dir()
    session_id = data.get("session_id", "") or ""

    # Init brain (idempotent)
    run_engine("init", project_dir)
    run_engine("init-run", project_dir, session_id)

    # Session warm-up: index project context for instant teammate access
    warmup(project_dir)

    # Read stats
    stats_raw = run_engine("status", project_dir)
    try:
        stats = json.loads(stats_raw)
    except Exception:
        stats = {}

    tasks = stats.get("tasks", 0)
    runs = stats.get("runs", 0)
    decisions = stats.get("decisions", 0)
    last = stats.get("last_activity", "") or ""

    teams_enabled = os.environ.get("CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS", "") == "1"

    # ── Solo mode context injection ──────────────────────────────────────────
    # Even without Agent Teams, inject previous session context into main Claude
    solo_context = ""
    if tasks > 0 and not teams_enabled:
        # Try "solo" role first (tasks indexed by current version)
        for role_query in ("solo", "main", ""):
            raw = run_engine("query-role", role_query, project_dir, "session start context")
            try:
                solo_context = json.loads(raw).get("additionalContext", "")
            except Exception:
                solo_context = ""
            if solo_context:
                break
        # role="" acts as a wildcard — matches all tasks regardless of role,
        # catching tasks indexed by older versions that stored empty agent_role

    # ── Status message ───────────────────────────────────────────────────────
    if tasks > 0:
        if teams_enabled:
            msg = (
                f"🧠 claude-teams-brain active: {tasks} tasks · {decisions} decisions · "
                f"{runs} sessions (last: {last}). "
                "Role-specific context will be auto-injected into each teammate on spawn."
            )
        else:
            msg = (
                f"🧠 claude-teams-brain active (solo mode): {tasks} tasks · "
                f"{decisions} decisions · {runs} sessions (last: {last}). "
                "Previous session context injected below."
            )
    else:
        if teams_enabled:
            msg = (
                "🧠 claude-teams-brain is installed and ready. "
                "Memory is empty for this project — it will build automatically "
                "as you run Agent Team sessions. Spawn your first team to get started."
            )
        else:
            msg = (
                "🧠 claude-teams-brain is installed (solo mode). "
                "Memory is empty — it will build automatically as you work. "
                "Your decisions, files, and context will be remembered across sessions."
            )

    # Solo mode tip (only shown when teams not enabled)
    if not teams_enabled:
        msg += (
            "\n💡 Solo mode active — memory builds from your own sessions. "
            "Add CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 to enable multi-agent teams."
        )

    # Version update hint
    update_hint = check_version()
    if update_hint:
        msg += f"\n{update_hint}"

    # Combine status message + solo context
    full_context = msg
    if solo_context:
        full_context += f"\n\n{solo_context}"

    emit_context("SessionStart", full_context)


def hook_session_end(data):
    project_dir = get_project_dir()
    session_id = data.get("session_id", "") or ""
    if session_id:
        run_engine("summarize-run", session_id, project_dir)


def hook_subagent_start(data):
    project_dir = get_project_dir()
    agent_type = (data.get("agent_type", "") or "general").lower().strip() or "general"

    task_desc = str(
        data.get("prompt") or data.get("task") or
        data.get("description") or data.get("message") or ""
    )[:500]

    context_raw = run_engine("query-role", agent_type, project_dir, task_desc)
    try:
        context = json.loads(context_raw).get("additionalContext", "")
    except Exception:
        context = ""

    full = f"{context}\n\n{TOOL_GUIDANCE}" if context else TOOL_GUIDANCE
    emit_context("SubagentStart", full)


def hook_subagent_stop(data):
    project_dir = get_project_dir()
    agent_name = data.get("agent_type", "") or "unknown"
    session_id = data.get("session_id", "") or ""
    transcript_path = data.get("agent_transcript_path", "") or ""
    last_message = data.get("last_assistant_message", "") or ""

    files_touched = []
    decisions = []
    output_summary = ""

    if transcript_path and Path(transcript_path).exists():
        try:
            entries = []
            with open(transcript_path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except Exception:
                            pass

            for entry in entries:
                msg = entry.get("message", {})
                content = msg.get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    # Capture file edits/writes
                    if block.get("type") == "tool_use" and block.get("name") in (
                        "Write", "Edit", "MultiEdit", "Create"
                    ):
                        fp = (
                            block.get("input", {}).get("file_path", "")
                            or block.get("input", {}).get("path", "")
                        )
                        if fp and fp not in files_touched:
                            files_touched.append(fp)
                    # Capture decision lines from text
                    if block.get("type") == "text":
                        for line in block.get("text", "").split("\n"):
                            lc = line.lower()
                            if any(
                                kw in lc for kw in [
                                    "decided to", "chose to", "will use",
                                    "approach:", "decision:", "rationale:",
                                ]
                            ):
                                clean = line.strip()[:200]
                                if clean and clean not in decisions:
                                    decisions.append(clean)

            if last_message:
                output_summary = last_message[:500]
            else:
                for entry in reversed(entries):
                    msg = entry.get("message", {})
                    if msg.get("role") == "assistant":
                        content_list = msg.get("content", [])
                        if not isinstance(content_list, list):
                            continue
                        for block in reversed(content_list):
                            if isinstance(block, dict) and block.get("type") == "text":
                                output_summary = block["text"][:500]
                                break
                        if output_summary:
                            break
        except Exception:
            pass

    if not output_summary and last_message:
        output_summary = last_message[:500]

    role = (
        re.sub(r"[-_]?(agent|teammate|worker|bot)$", "", agent_name, flags=re.I).strip()
        or agent_name
    )

    payload = {
        "project_dir": project_dir,
        "run_id": session_id,
        "session_id": session_id,
        "task_subject": f"Work by {agent_name}",
        "agent_name": agent_name,
        "agent_role": role,
        "files_touched": files_touched[:50],
        "decisions": decisions[:20],
        "output_summary": output_summary,
    }
    run_engine("index-task", input_data=json.dumps(payload))


def hook_task_completed(data):
    project_dir = get_project_dir()
    task_subject = data.get("task_subject") or data.get("task_description") or ""
    agent_name = data.get("agent_name") or data.get("teammate_name") or ""
    session_id = data.get("session_id") or ""
    task_id = data.get("task_id") or ""

    role = (
        re.sub(r"[-_]?(agent|teammate|worker|bot)$", "", agent_name, flags=re.I).strip()
        or agent_name
    )

    # In solo mode (no agent running), agent_name and role are both empty.
    # Tag these tasks as "solo" so hook_session_start can find them via query-role.
    if not agent_name:
        agent_name = "solo"
    if not role:
        role = "solo"

    payload = {
        "project_dir": project_dir,
        "run_id": session_id,
        "session_id": session_id,
        "task_subject": task_subject,
        "agent_name": agent_name,
        "agent_role": role,
        "task_id": task_id,
        "files_touched": [],
        "decisions": [],
        "output_summary": task_subject,
    }
    run_engine("index-task", input_data=json.dumps(payload))

    if task_subject:
        prefix = f"[{agent_name}] " if agent_name not in ("solo", "") else ""
        emit_context("TaskCompleted", f"🧠 Indexed: {prefix}{task_subject}")


def hook_teammate_idle(data):
    pass  # passive checkpoint — no action needed


def hook_pretooluse_task(data):
    project_dir = get_project_dir()
    tool_input = data.get("tool_input", {}) or {}
    description = tool_input.get("description", "") or ""
    if not description:
        return

    context_raw = run_engine("query-role", "general", project_dir, description)
    try:
        context = json.loads(context_raw).get("additionalContext", "")
    except Exception:
        context = ""

    if context:
        emit_context("PreToolUse", context)


# ── Entrypoint ─────────────────────────────────────────────────────────────────

HANDLERS = {
    "session-start":   hook_session_start,
    "session-end":     hook_session_end,
    "subagent-start":  hook_subagent_start,
    "subagent-stop":   hook_subagent_stop,
    "task-completed":  hook_task_completed,
    "teammate-idle":   hook_teammate_idle,
    "pretooluse-task": hook_pretooluse_task,
}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    event = sys.argv[1].lower().replace("_", "-")
    data = read_input()

    handler = HANDLERS.get(event)
    if handler:
        try:
            handler(data)
        except Exception as e:
            # Never crash — hooks must always exit 0
            print(f"[claude-teams-brain] hook error ({event}): {e}", file=sys.stderr)
    else:
        print(f"[claude-teams-brain] unknown event: {event}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
