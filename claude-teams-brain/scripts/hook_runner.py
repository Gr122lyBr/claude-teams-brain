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


# Expanded set of decision signal phrases
DECISION_KEYWORDS = [
    # Explicit decision markers
    "decided to", "decided that", "we decided", "i decided",
    "chose to", "choice:", "selected ",
    "opted for", "going with",
    "will use", "should use", "must use",
    # Structural markers
    "approach:", "decision:", "rationale:", "reason:",
    "note:", "convention:", "rule:", "key decision",
    "important:", "pattern:", "strategy:",
    # Change / migration markers
    "switched to", "migrated to", "refactored to",
    "instead of", "rather than", "replacing",
    # Future intent
    "we'll use", "i'll use", "we will use",
]


def extract_decisions_from_text(text, max_chars=500):
    """Extract decision-like lines from text using expanded keyword matching."""
    decisions = []
    for line in text.split("\n"):
        lc = line.lower().strip()
        if not lc or len(lc) < 10:
            continue
        if any(kw in lc for kw in DECISION_KEYWORDS):
            clean = line.strip()[:max_chars]
            if clean and clean not in decisions:
                decisions.append(clean)
    return decisions


def extract_decisions_llm(text: str, timeout: int = 8) -> list:
    """Extract decisions via Claude API if ANTHROPIC_API_KEY is available. Falls back silently."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key or not text.strip():
        return []
    try:
        import urllib.request as urlreq
        payload = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 300,
            "messages": [{
                "role": "user",
                "content": (
                    "Extract key technical decisions from this text. "
                    "Return ONLY a JSON array of short strings (max 15 words each). "
                    "Include only concrete decisions (what was chosen, built, or changed). "
                    "If no decisions, return [].\n\n"
                    f"{text[:1500]}"
                )
            }]
        }).encode()
        req = urlreq.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
        )
        with urlreq.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read())
            raw = result['content'][0]['text'].strip()
            # Strip markdown code fences if present
            raw = re.sub(r'^```[a-z]*\n?', '', raw)
            raw = re.sub(r'\n?```$', '', raw)
            decisions = json.loads(raw)
            if isinstance(decisions, list):
                return [str(d)[:500] for d in decisions if isinstance(d, str) and d.strip()]
    except Exception:
        pass
    return []


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


def detect_stack(project_dir: str) -> str:
    """Detect project stack from files. Returns profile name or empty string."""
    root = Path(project_dir)
    try:
        pkg_path = root / 'package.json'
        if pkg_path.exists():
            pkg = pkg_path.read_text(encoding='utf-8', errors='ignore').lower()
            if 'react-native' in pkg or '"expo"' in pkg:
                return 'react-native'
            if '"next"' in pkg or 'nextjs' in pkg:
                return 'nextjs-prisma'

        for fname in ['requirements.txt', 'pyproject.toml', 'setup.py']:
            fpath = root / fname
            if fpath.exists():
                content = fpath.read_text(encoding='utf-8', errors='ignore').lower()
                if 'fastapi' in content:
                    return 'fastapi'
                return 'python-general'

        if (root / 'go.mod').exists():
            return 'go-microservices'
    except Exception:
        pass
    return ''


def warmup(project_dir):
    """Index project context sources into the session KB. Returns list of indexed source names."""
    indexed = []

    # 1. CLAUDE.md
    claude_md = Path(project_dir) / "CLAUDE.md"
    if claude_md.exists() and claude_md.stat().st_size > 200:
        run_engine("kb-index", project_dir, "CLAUDE.md", str(claude_md))
        indexed.append("CLAUDE.md")

    # 2. Git history
    try:
        result = subprocess.run(
            ["git", "-C", project_dir, "log", "--oneline", "-20"],
            capture_output=True, text=True, timeout=10,
        )
        if result.stdout.strip():
            index_text(project_dir, "git-log", result.stdout)
            indexed.append("git-log")
    except Exception:
        pass

    # 3. Directory tree (pure Python — works on all platforms)
    try:
        tree = dir_tree(project_dir)
        if tree:
            index_text(project_dir, "directory-tree", tree)
            indexed.append("dir-tree")
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
            indexed.append(cfg)

    # 5. Auto-seed from existing convention files (zero-config onboarding)
    for conv_file in [".cursorrules", "AGENTS.md", "CONVENTIONS.md"]:
        conv_path = Path(project_dir) / conv_file
        if conv_path.exists() and conv_path.stat().st_size > 100:
            run_engine("kb-index", project_dir, conv_file, str(conv_path))
            indexed.append(conv_file)

    # 6. Auto-seed stack conventions if brain has no existing memories
    try:
        status_raw = run_engine("status", project_dir)
        status = json.loads(status_raw) if status_raw else {}
        if status.get("decisions", 0) == 0:
            profile = detect_stack(project_dir)
            if profile:
                run_engine("seed-profile", profile, project_dir)
                index_text(project_dir, "auto-stack", f"Auto-detected stack: {profile}. Conventions seeded.")
                indexed.append(f"stack:{profile}")
    except Exception:
        pass

    return indexed


TOOL_GUIDANCE = """\
## Token-Efficient Tools (claude-teams-brain)

You have five MCP tools that keep large output OUT of your context window. Use them instead of Bash whenever output could be large.

**`batch_execute`** — default for shell commands
- Use for 2+ commands; all output auto-indexed, never floods context
- Always include `queries` to immediately search indexed output
- Example: `batch_execute(commands=[{"label":"tests","command":"npm test"},{"label":"log","command":"git log --oneline -20"}], queries=["failing tests","recent changes"])`

**`execute`** — single command or code snippet
- Set `intent` when output may be large — auto-indexes and searches instead of returning raw output
- Example: `execute(language="python", code="...", intent="find all class definitions")`

**`search`** — query already-indexed output without re-running commands
- Example: `search(queries=["auth middleware","error handling"])`

**`index`** — save findings for yourself and teammates
- Example: `index(content="Auth uses RS256 JWT, 15min expiry", source="auth-analysis")`

**`stats`** — check context savings at end of investigation

Standard workflow: `batch_execute` → `search` → `index`
All teammates share the same session KB — index once, any teammate can search it."""

# Role keyword mapping for inference
ROLE_KEYWORDS = {
    'frontend':  ['react', 'vue', 'angular', 'css', 'html', 'tailwind', 'component', 'ui ', 'layout', 'style'],
    'backend':   ['api', 'server', 'endpoint', 'route', 'middleware', 'express', 'fastapi', 'django', 'rest'],
    'database':  ['sql', 'migration', 'schema', 'postgres', 'mysql', 'sqlite', 'prisma', 'orm', 'query', 'seed'],
    'tests':     ['test', 'spec', 'jest', 'pytest', 'coverage', 'mock', 'assert', 'unit', 'integration', 'e2e'],
    'devops':    ['docker', 'kubernetes', 'deploy', 'pipeline', 'ci/cd', 'nginx', 'github action', 'terraform'],
    'security':  ['auth', 'jwt', 'oauth', 'permission', 'encrypt', 'hash', 'csrf', 'xss', 'vulnerab'],
    'architect': ['architecture', 'design', 'refactor', 'structure', 'pattern', 'monolith', 'microservice'],
}


def infer_role(role: str, task_desc: str) -> str:
    """If role is generic, infer from task description keywords."""
    if role and role not in ('general', 'unknown', ''):
        return role
    desc_lower = task_desc.lower()
    scores = {}
    for candidate, keywords in ROLE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in desc_lower)
        if score > 0:
            scores[candidate] = score
    if scores:
        return max(scores, key=scores.get)
    return role or 'general'


# ── Hook handlers ──────────────────────────────────────────────────────────────

def hook_session_start(data):
    project_dir = get_project_dir()
    session_id = data.get("session_id", "") or ""

    # Init brain (idempotent)
    run_engine("init", project_dir)
    run_engine("init-run", project_dir, session_id)

    # Session warm-up: index project context for instant teammate access
    kb_sources = warmup(project_dir)

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
    kb_line = f"KB warmed: {' · '.join(kb_sources[:6])}" if kb_sources else ""

    if tasks > 0:
        if teams_enabled:
            msg = (
                f"🧠 claude-teams-brain active\n"
                f"Memory: {tasks} tasks · {decisions} decisions · {runs} sessions (last: {last})\n"
                + (f"{kb_line}\n" if kb_line else "")
                + "Role-specific context will be auto-injected into each teammate on spawn."
            )
        else:
            msg = (
                f"🧠 claude-teams-brain active (solo mode)\n"
                f"Memory: {tasks} tasks · {decisions} decisions · {runs} sessions (last: {last})\n"
                + (f"{kb_line}\n" if kb_line else "")
                + "Previous session context injected below."
            )
    else:
        if teams_enabled:
            msg = (
                "🧠 claude-teams-brain is installed and ready.\n"
                "Memory is empty for this project — it will build automatically "
                "as you run Agent Team sessions.\n"
                + (f"{kb_line}\n" if kb_line else "")
                + "Spawn your first team to get started."
            )
        else:
            msg = (
                "🧠 claude-teams-brain is installed (solo mode).\n"
                "Memory is empty — it will build automatically as you work.\n"
                + (f"{kb_line}\n" if kb_line else "")
                + "Your decisions, files, and context will be remembered across sessions."
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

    # ── User-visible banner (stderr → terminal) ────────────────────────────
    banner_parts = ["🧠 claude-teams-brain warming up..."]
    if kb_sources:
        banner_parts.append(f"   Indexed: {', '.join(kb_sources[:6])}")
    if tasks > 0:
        banner_parts.append(f"   Memory: {tasks} tasks · {decisions} decisions · {runs} sessions")
    else:
        banner_parts.append("   Memory: empty (will build as you work)")
    if not teams_enabled:
        banner_parts.append("   Mode: solo (set CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1 for teams)")
    update_hint_banner = check_version()
    if update_hint_banner:
        banner_parts.append(f"   {update_hint_banner}")
    banner_parts.append("🧠 Brain ready.")
    print("\n".join(banner_parts), file=sys.stderr)

    # Build a short user-facing banner the model should display immediately
    display_banner = f"🧠 **claude-teams-brain** active"
    if tasks > 0:
        display_banner += f" — {tasks} tasks · {decisions} decisions · {runs} sessions"
    else:
        display_banner += " — memory empty (will build as you work)"
    if kb_sources:
        display_banner += f"\n   KB warmed: {', '.join(kb_sources[:6])}"
    if update_hint:
        display_banner += f"\n   {update_hint}"

    display_instruction = (
        "\n\n**IMPORTANT — Display to user**: At the very start of your first response "
        "(before any other output), display the following status line exactly as-is, "
        "then proceed with whatever the user asked:\n\n"
        f"{display_banner}\n"
    )

    full_context = msg + display_instruction + "\n\n" + TOOL_GUIDANCE
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

    # Infer role from task description if agent_type is generic
    agent_type = infer_role(agent_type, task_desc)

    context_raw = run_engine("query-role", agent_type, project_dir, task_desc)
    try:
        context = json.loads(context_raw).get("additionalContext", "")
    except Exception:
        context = ""

    if context:
        header = f"🧠 Brain → [{agent_type}] context loaded from memory"
        full = f"{header}\n\n{context}\n\n{TOOL_GUIDANCE}"
    else:
        header = f"🧠 Brain → [{agent_type}] (no prior history for this role — memory will build after this session)"
        full = f"{header}\n\n{TOOL_GUIDANCE}"
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
                    # Capture decision lines from text blocks
                    if block.get("type") == "text":
                        for d in extract_decisions_from_text(block.get("text", "")):
                            if d not in decisions:
                                decisions.append(d)
                    # Capture decisions from comments inside written/edited files
                    if block.get("type") == "tool_use" and block.get("name") in (
                        "Write", "Edit", "MultiEdit",
                    ):
                        inp = block.get("input", {})
                        file_content = (
                            inp.get("new_string", "") or inp.get("content", "") or ""
                        )
                        if file_content:
                            comment_lines = "\n".join(
                                ln for ln in file_content.split("\n")
                                if ln.strip().startswith(("#", "//", "*", "/*"))
                            )
                            for d in extract_decisions_from_text(comment_lines):
                                if d not in decisions:
                                    decisions.append(d)

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
    # Infer role if still generic
    hint = last_message[:500] if last_message else ""
    role = infer_role(role, hint)

    # Enhance decisions with LLM extraction if API key available
    if output_summary:
        llm_decisions = extract_decisions_llm(output_summary)
        for d in llm_decisions:
            if d not in decisions:
                decisions.append(d)

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

    # Emit brief confirmation so the user sees the brain captured the agent's work
    decision_note = f" · {len(decisions)} decision(s) captured" if decisions else ""
    file_note = f" · {len(files_touched)} file(s) tracked" if files_touched else ""
    emit_context("SubagentStop", f"🧠 [{agent_name}] work indexed{decision_note}{file_note}")


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

    # Extract decisions from all available text in the event payload
    all_text = "\n".join(filter(None, [
        task_subject,
        data.get("output", "") or "",
        data.get("result", "") or "",
        data.get("description", "") or "",
    ]))
    decisions = extract_decisions_from_text(all_text)

    # Accept files_touched if the event provides them (future-proof)
    files_touched = list(data.get("files_touched") or [])

    payload = {
        "project_dir": project_dir,
        "run_id": session_id,
        "session_id": session_id,
        "task_subject": task_subject,
        "agent_name": agent_name,
        "agent_role": role,
        "task_id": task_id,
        "files_touched": files_touched,
        "decisions": decisions,
        "output_summary": task_subject,
    }
    run_engine("index-task", input_data=json.dumps(payload))

    if task_subject:
        prefix = f"[{agent_name}] " if agent_name not in ("solo", "") else ""
        decision_note = f" · {len(decisions)} decision(s)" if decisions else ""
        emit_context("TaskCompleted", f"🧠 Indexed: {prefix}{task_subject}{decision_note}")


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


# Commands that tend to produce large output — worth redirecting to brain tools
_LARGE_OUTPUT_CMDS = [
    "npm test", "npm run", "yarn test", "yarn run", "pnpm test", "pnpm run",
    "pytest", "jest", "vitest", "cargo test", "go test",
    "git log", "git diff", "git show", "git blame",
    "grep", "rg ", "ripgrep", "find ",
    "cat ", "head ", "tail ",
    "docker", "kubectl", "helm",
    "pip list", "npm list", "yarn list",
    "ps aux", "netstat", "lsof", "df ", "du ",
]


def hook_pretooluse_bash(data):
    tool_input = data.get("tool_input", {}) or {}
    command = (tool_input.get("command", "") or "").lower()
    if not command:
        return

    if any(pat in command for pat in _LARGE_OUTPUT_CMDS):
        emit_context("PreToolUse", (
            "💡 brain tip: This command may produce large output. "
            "Use `batch_execute` (2+ commands) or `execute(intent=\"...\")` (1 command) "
            "— output is auto-indexed, only relevant snippets enter context."
        ))


def hook_pretooluse_read(data):
    tool_input = data.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path", "") or ""
    limit = tool_input.get("limit")

    # Only tip when reading an entire file (no limit scoping)
    if not file_path or limit:
        return

    emit_context("PreToolUse", (
        "💡 brain tip: For large files use "
        "`execute(language=\"shell\", code=\"cat <file>\", intent=\"what you need\")` "
        "— auto-indexes content, only relevant snippets enter context."
    ))


# ── Entrypoint ─────────────────────────────────────────────────────────────────

HANDLERS = {
    "session-start":    hook_session_start,
    "session-end":      hook_session_end,
    "subagent-start":   hook_subagent_start,
    "subagent-stop":    hook_subagent_stop,
    "task-completed":   hook_task_completed,
    "teammate-idle":    hook_teammate_idle,
    "pretooluse-task":  hook_pretooluse_task,
    "pretooluse-bash":  hook_pretooluse_bash,
    "pretooluse-read":  hook_pretooluse_read,
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
