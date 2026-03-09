#!/usr/bin/env python3
"""
claude-brain engine
Persistent memory store for Claude Code Agent Teams.
Uses only Python stdlib — no external dependencies.

Usage:
  brain_engine.py init <project_dir>
  brain_engine.py init-run <project_dir> [<session_id>]
  brain_engine.py index-task <json>
  brain_engine.py query-role <role> [<project_dir>]
  brain_engine.py status [<project_dir>]
  brain_engine.py summarize-run <run_id> [<project_dir>]
  brain_engine.py list-runs [<project_dir>]
  brain_engine.py clear [<project_dir>]
  brain_engine.py kb-index <project_dir> <source> <content_file>
  brain_engine.py kb-search <project_dir> <query> [<limit>]
  brain_engine.py kb-stats <project_dir>
"""

import sys
import os
import json
import sqlite3
import hashlib
import re
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
BRAIN_HOME = Path(os.environ.get("CLAUDE_BRAIN_HOME", Path.home() / ".claude-teams-brain"))
CONTEXT_BUDGET = int(os.environ.get('CLAUDE_BRAIN_CONTEXT_BUDGET', '3000'))


def project_id(project_dir: str) -> str:
    """Stable identifier for a project directory."""
    return hashlib.sha256(str(Path(project_dir).resolve()).encode()).hexdigest()[:12]


def db_path(project_dir: str) -> Path:
    pid = project_id(project_dir)
    path = BRAIN_HOME / "projects" / pid
    path.mkdir(parents=True, exist_ok=True)
    return path / "brain.db"


# ── Schema ────────────────────────────────────────────────────────────────────
SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS runs (
    id          TEXT PRIMARY KEY,
    project_dir TEXT NOT NULL,
    session_id  TEXT,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    summary     TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id             TEXT PRIMARY KEY,
    run_id         TEXT REFERENCES runs(id),
    task_subject   TEXT,
    agent_name     TEXT,
    agent_role     TEXT,
    files_touched  TEXT DEFAULT '[]',
    decisions      TEXT DEFAULT '[]',
    output_summary TEXT,
    completed_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id          TEXT PRIMARY KEY,
    run_id      TEXT REFERENCES runs(id),
    agent_name  TEXT,
    context     TEXT,
    decision    TEXT NOT NULL,
    rationale   TEXT,
    tags        TEXT DEFAULT '[]',
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS file_index (
    id         TEXT PRIMARY KEY,
    task_id    TEXT REFERENCES tasks(id),
    run_id     TEXT,
    file_path  TEXT NOT NULL,
    operation  TEXT,
    agent_name TEXT,
    summary    TEXT,
    touched_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS kb_chunks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    content_type TEXT DEFAULT 'text',
    bytes INTEGER NOT NULL,
    indexed_at TEXT NOT NULL DEFAULT (datetime('now','utc'))
);

CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
    title, content,
    chunk_id UNINDEXED,
    tokenize='porter unicode61'
);

CREATE TRIGGER IF NOT EXISTS kb_fts_ai AFTER INSERT ON kb_chunks BEGIN
    INSERT INTO kb_fts(rowid, title, content, chunk_id) VALUES (new.id, new.title, new.content, new.id);
END;

-- Full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts USING fts5(
    task_subject, output_summary, decisions, agent_role,
    content=tasks, content_rowid=rowid
);

CREATE TRIGGER IF NOT EXISTS tasks_fts_insert AFTER INSERT ON tasks BEGIN
    INSERT INTO tasks_fts(rowid, task_subject, output_summary, decisions, agent_role)
    VALUES (new.rowid, new.task_subject, new.output_summary, new.decisions, new.agent_role);
END;

CREATE TRIGGER IF NOT EXISTS tasks_fts_update AFTER UPDATE ON tasks BEGIN
    UPDATE tasks_fts SET
        task_subject   = new.task_subject,
        output_summary = new.output_summary,
        decisions      = new.decisions,
        agent_role     = new.agent_role
    WHERE rowid = new.rowid;
END;
"""

# Trigram FTS table — requires SQLite with trigram tokenizer support
TRIGRAM_SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS tasks_fts_trigram USING fts5(
    content,
    tokenize='trigram'
);

CREATE TRIGGER IF NOT EXISTS tasks_fts_trigram_insert AFTER INSERT ON tasks BEGIN
    INSERT INTO tasks_fts_trigram(content)
    VALUES (COALESCE(new.task_subject, '') || ' ' || COALESCE(new.output_summary, '') || ' ' || COALESCE(new.decisions, '') || ' ' || COALESCE(new.agent_role, ''));
END;

CREATE TRIGGER IF NOT EXISTS tasks_fts_trigram_update AFTER UPDATE ON tasks BEGIN
    DELETE FROM tasks_fts_trigram WHERE rowid = new.rowid;
    INSERT INTO tasks_fts_trigram(rowid, content)
    VALUES (new.rowid, COALESCE(new.task_subject, '') || ' ' || COALESCE(new.output_summary, '') || ' ' || COALESCE(new.decisions, '') || ' ' || COALESCE(new.agent_role, ''));
END;
"""


_trigram_available = None  # cached after first check


def get_conn(project_dir: str) -> sqlite3.Connection:
    global _trigram_available
    path = db_path(project_dir)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()

    # Try to create trigram FTS table (may fail on older SQLite builds)
    if _trigram_available is None:
        try:
            conn.executescript(TRIGRAM_SCHEMA)
            conn.commit()
            _trigram_available = True
        except Exception as e:
            _trigram_available = False
            print(f"[claude-brain] trigram tokenizer not available, skipping: {e}", file=sys.stderr)
    elif _trigram_available:
        try:
            conn.executescript(TRIGRAM_SCHEMA)
            conn.commit()
        except Exception:
            pass

    # KB trigram FTS (graceful fallback if SQLite < 3.34)
    try:
        conn.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts_trigram USING fts5(
            title, content, chunk_id UNINDEXED, tokenize='trigram')""")
        conn.execute("""CREATE TRIGGER IF NOT EXISTS kb_fts_trigram_ai AFTER INSERT ON kb_chunks BEGIN
            INSERT INTO kb_fts_trigram(rowid, title, content, chunk_id) VALUES (new.id, new.title, new.content, new.id);
        END""")
        conn.commit()
    except Exception:
        pass

    return conn


def ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def uid() -> str:
    import secrets
    return secrets.token_hex(8)


# ── Search helpers ────────────────────────────────────────────────────────────

def search_with_fallback(conn, query, limit=5):
    """Three-layer search: porter stemming -> trigram -> word-by-word."""
    # Layer 1: Porter stemming FTS5
    try:
        rows = conn.execute(
            "SELECT content, rank FROM tasks_fts WHERE tasks_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit)
        ).fetchall()
        if rows:
            return [r[0] for r in rows]
    except Exception:
        pass

    # Layer 2: Trigram substring
    try:
        rows = conn.execute(
            "SELECT content, rank FROM tasks_fts_trigram WHERE tasks_fts_trigram MATCH ? ORDER BY rank LIMIT ?",
            (query, limit)
        ).fetchall()
        if rows:
            return [r[0] for r in rows]
    except Exception:
        pass

    # Layer 3: Word-by-word (split query, search each word)
    results = []
    seen = set()
    for word in query.lower().split():
        if len(word) <= 3:
            continue
        try:
            rows = conn.execute(
                "SELECT content FROM tasks_fts WHERE tasks_fts MATCH ? ORDER BY rank LIMIT ?",
                (word, limit)
            ).fetchall()
            for row in rows:
                if row[0] not in seen:
                    seen.add(row[0])
                    results.append(row[0])
        except Exception:
            pass
    return results[:limit]


def extract_snippet(content, query, max_len=800):
    """Extract relevant windows around query terms instead of full content."""
    if not content or len(content) <= max_len:
        return content

    query_terms = [t for t in query.lower().split() if len(t) > 2]
    content_lower = content.lower()

    # Find match positions
    positions = []
    for term in query_terms:
        pos = content_lower.find(term)
        while pos != -1:
            positions.append(pos)
            pos = content_lower.find(term, pos + 1)

    if not positions:
        return content[:max_len] + ("\u2026" if len(content) > max_len else "")

    # Create merged windows (+-300 chars around each match)
    WINDOW = 300
    windows = []
    for pos in sorted(positions):
        start = max(0, pos - WINDOW)
        end = min(len(content), pos + WINDOW)
        if windows and start <= windows[-1][1]:
            windows[-1] = (windows[-1][0], end)
        else:
            windows.append([start, end])

    # Collect parts until max_len
    parts = []
    total = 0
    for start, end in windows:
        if total >= max_len:
            break
        chunk = content[start:min(end, start + (max_len - total))]
        prefix = "\u2026" if start > 0 else ""
        suffix = "\u2026" if end < len(content) else ""
        parts.append(prefix + chunk + suffix)
        total += len(chunk)

    return "\n\n".join(parts)


def chunk_content(content, source):
    """Split content into chunks by markdown headings or fixed line groups."""
    chunks = []
    lines = content.split('\n')
    heading_stack = []
    current_lines = []

    def flush(title_override=None):
        if not current_lines:
            return
        body = '\n'.join(current_lines).strip()
        if not body:
            return
        if title_override:
            title = title_override
        elif heading_stack:
            title = ' / '.join(h for _, h in heading_stack)
        else:
            title = source
        chunks.append({'title': title, 'content': body})
        current_lines.clear()

    for line in lines:
        m = re.match(r'^(#{1,4})\s+(.+)', line)
        if m:
            flush()
            level = len(m.group(1))
            text = m.group(2).strip()
            # Pop stack to current level
            heading_stack[:] = [(l, t) for l, t in heading_stack if l < level]
            heading_stack.append((level, text))
        elif line.strip() == '---':
            flush()
        else:
            current_lines.append(line)
    flush()

    # If no chunks produced (plain text), use fixed 30-line groups
    if not chunks:
        for i in range(0, len(lines), 30):
            group = '\n'.join(lines[i:i+30]).strip()
            if group:
                chunks.append({'title': f'{source} (lines {i+1}-{i+30})', 'content': group})

    return chunks


def kb_search_query(conn, query, limit=5):
    """Three-layer search against kb_fts."""
    # Layer 1: Porter stemming
    try:
        rows = conn.execute(
            "SELECT kc.title, kc.content, kc.source FROM kb_fts kf JOIN kb_chunks kc ON kf.rowid = kc.id WHERE kb_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit)
        ).fetchall()
        if rows:
            return rows
    except Exception:
        pass

    # Layer 2: Trigram
    try:
        rows = conn.execute(
            "SELECT kc.title, kc.content, kc.source FROM kb_fts_trigram kf JOIN kb_chunks kc ON kf.rowid = kc.id WHERE kb_fts_trigram MATCH ? ORDER BY rank LIMIT ?",
            (query, limit)
        ).fetchall()
        if rows:
            return rows
    except Exception:
        pass

    # Layer 3: Word-by-word
    results, seen = [], set()
    for word in query.lower().split():
        if len(word) <= 3:
            continue
        try:
            rows = conn.execute(
                "SELECT kc.title, kc.content, kc.source FROM kb_fts kf JOIN kb_chunks kc ON kf.rowid = kc.id WHERE kb_fts MATCH ? ORDER BY rank LIMIT ?",
                (word, limit)
            ).fetchall()
            for row in rows:
                if row[1] not in seen:
                    seen.add(row[1])
                    results.append(row)
        except Exception:
            pass
    return results[:limit]


# ── Commands ──────────────────────────────────────────────────────────────────

def cmd_init(project_dir: str):
    """Initialize or migrate the brain for a project."""
    conn = get_conn(project_dir)
    pid = project_id(project_dir)
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('project_dir', ?)", (project_dir,))
    conn.execute("INSERT OR REPLACE INTO meta VALUES ('initialized_at', ?)", (ts(),))
    conn.commit()
    conn.close()
    print(json.dumps({
        "status": "ok",
        "project_id": pid,
        "db_path": str(db_path(project_dir))
    }))


def cmd_index_task(payload_str: str):
    """
    Index a completed task.
    Payload fields:
      project_dir, run_id, session_id, task_subject, agent_name,
      agent_role, files_touched (list), decisions (list),
      output_summary
    """
    p = json.loads(payload_str)
    project_dir = p.get("project_dir", os.getcwd())
    conn = get_conn(project_dir)

    # Ensure run exists
    run_id = p.get("run_id") or p.get("session_id") or uid()
    existing = conn.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO runs (id, project_dir, session_id, started_at) VALUES (?,?,?,?)",
            (run_id, project_dir, p.get("session_id"), ts())
        )

    task_id = uid()
    files = json.dumps(p.get("files_touched", []))
    decisions = json.dumps(p.get("decisions", []))

    conn.execute(
        """INSERT INTO tasks
           (id, run_id, task_subject, agent_name, agent_role,
            files_touched, decisions, output_summary, completed_at)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (task_id, run_id,
         p.get("task_subject", ""), p.get("agent_name", ""), p.get("agent_role", ""),
         files, decisions, p.get("output_summary", ""), ts())
    )

    # Index individual files
    for fp in p.get("files_touched", []):
        conn.execute(
            """INSERT INTO file_index
               (id, task_id, run_id, file_path, operation, agent_name, summary, touched_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            (uid(), task_id, run_id, fp,
             p.get("operation", "edit"), p.get("agent_name", ""),
             p.get("output_summary", ""), ts())
        )

    # Index decisions
    for d in p.get("decisions", []):
        if isinstance(d, str):
            dec_text, rationale = d, ""
        elif isinstance(d, dict):
            dec_text = d.get("decision", str(d))
            rationale = d.get("rationale", "")
        else:
            continue
        conn.execute(
            """INSERT INTO decisions
               (id, run_id, agent_name, decision, rationale, created_at)
               VALUES (?,?,?,?,?,?)""",
            (uid(), run_id, p.get("agent_name", ""), dec_text, rationale, ts())
        )

    conn.commit()
    conn.close()
    print(json.dumps({"status": "ok", "task_id": task_id}))


def cmd_query_role(role: str, project_dir: str):
    """
    Return memory relevant to a role.
    Used by SubagentStart to inject context into a new teammate.
    Output is a formatted string ready to inject as additionalContext.
    """
    conn = get_conn(project_dir)
    role_lower = role.lower()

    # Recent tasks for this role (last 10)
    role_tasks = conn.execute(
        """SELECT t.task_subject, t.output_summary, t.files_touched, t.decisions,
                  t.completed_at, t.run_id
           FROM tasks t
           WHERE lower(t.agent_role) LIKE ? OR lower(t.agent_name) LIKE ?
           ORDER BY t.completed_at DESC LIMIT 10""",
        (f"%{role_lower}%", f"%{role_lower}%")
    ).fetchall()

    # Also try FTS fallback search for the role
    fts_results = search_with_fallback(conn, role, limit=5)

    # Recent decisions (last 15, any role — shared knowledge)
    all_decisions = conn.execute(
        """SELECT d.decision, d.rationale, d.agent_name, d.created_at
           FROM decisions d
           ORDER BY d.created_at DESC LIMIT 15"""
    ).fetchall()

    # Files this role has touched
    role_files = conn.execute(
        """SELECT DISTINCT fi.file_path, fi.summary
           FROM file_index fi
           WHERE lower(fi.agent_name) LIKE ?
           ORDER BY fi.touched_at DESC LIMIT 20""",
        (f"%{role_lower}%",)
    ).fetchall()

    # Recent run summary
    last_run = conn.execute(
        "SELECT summary, started_at FROM runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()

    conn.close()

    if not role_tasks and not all_decisions and not fts_results:
        print(json.dumps({"additionalContext": ""}))
        return

    lines = [
        f"## 🧠 claude-brain: Memory for role [{role}]",
        f"_Auto-injected context from past Agent Team sessions_",
        "",
    ]

    if last_run and last_run["summary"]:
        lines += ["### Last Session Summary", last_run["summary"], ""]

    if role_tasks:
        lines.append("### Your Past Work")
        for t in role_tasks[:5]:
            subj = t["task_subject"] or "(no subject)"
            snippet = extract_snippet(t["output_summary"] or "", role)
            files = json.loads(t["files_touched"] or "[]")
            decisions = json.loads(t["decisions"] or "[]")
            short_id = (t["run_id"] or "")[:8]

            lines.append(f"**{subj}** (session {short_id})")
            if snippet:
                lines.append(snippet)
            if files:
                lines.append(f"Key files: {', '.join(files[:5])}")
            if decisions:
                dec_strs = [d if isinstance(d, str) else d.get("decision", str(d)) for d in decisions[:3]]
                lines.append(f"Key decisions: {'; '.join(dec_strs)}")
            lines.append("")

    if all_decisions:
        lines.append("### Key Decisions Made by the Team")
        for d in all_decisions[:10]:
            dec = d["decision"][:200]
            by = d["agent_name"] or "team"
            lines.append(f"- [{by}] {dec}")
        lines.append("")

    if role_files:
        lines.append("### Files You've Worked On")
        for f in role_files[:10]:
            lines.append(f"- `{f['file_path']}`")
        lines.append("")

    lines.append("_Use this context to avoid duplicating work and maintain consistency._")

    context = "\n".join(lines)

    # Apply context budget cap
    if len(context) > CONTEXT_BUDGET:
        context = context[:CONTEXT_BUDGET] + "\n\n_[Truncated — context budget of {} chars reached]_".format(CONTEXT_BUDGET)

    print(json.dumps({"additionalContext": context}))


def cmd_status(project_dir: str):
    """Print brain stats as JSON."""
    conn = get_conn(project_dir)
    stats = {
        "project_id": project_id(project_dir),
        "db_path": str(db_path(project_dir)),
        "runs": conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
        "tasks": conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
        "decisions": conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0],
        "files_indexed": conn.execute("SELECT COUNT(DISTINCT file_path) FROM file_index").fetchone()[0],
        "agents_seen": conn.execute("SELECT COUNT(DISTINCT agent_name) FROM tasks WHERE agent_name != ''").fetchone()[0],
        "last_activity": conn.execute("SELECT MAX(completed_at) FROM tasks").fetchone()[0],
    }
    conn.close()
    print(json.dumps(stats, indent=2))


def cmd_summarize_run(run_id: str, project_dir: str):
    """Generate and store a summary of a completed run."""
    conn = get_conn(project_dir)

    tasks = conn.execute(
        "SELECT * FROM tasks WHERE run_id = ? ORDER BY completed_at",
        (run_id,)
    ).fetchall()

    decisions = conn.execute(
        "SELECT * FROM decisions WHERE run_id = ? ORDER BY created_at",
        (run_id,)
    ).fetchall()

    if not tasks:
        conn.close()
        print(json.dumps({"status": "no_tasks"}))
        return

    lines = []
    agents = list(set(t["agent_name"] for t in tasks if t["agent_name"]))
    lines.append(f"Team: {', '.join(agents)}")
    lines.append(f"Tasks completed: {len(tasks)}")

    for t in tasks:
        lines.append(f"- [{t['agent_name']}] {t['task_subject']}: {(t['output_summary'] or '')[:150]}")

    if decisions:
        lines.append(f"Decisions: {len(decisions)}")
        for d in decisions[:5]:
            lines.append(f"  * {d['decision'][:100]}")

    summary = "\n".join(lines)
    conn.execute("UPDATE runs SET summary = ?, ended_at = ? WHERE id = ?",
                 (summary, ts(), run_id))
    conn.commit()
    conn.close()
    print(json.dumps({"status": "ok", "summary": summary}))


def cmd_list_runs(project_dir: str):
    """List past runs with task counts and agents involved."""
    conn = get_conn(project_dir)
    runs = conn.execute(
        "SELECT id, started_at, ended_at, summary FROM runs ORDER BY started_at DESC LIMIT 20"
    ).fetchall()
    result = []
    for r in runs:
        row = dict(r)
        counts = conn.execute(
            "SELECT COUNT(*) as tasks, COUNT(DISTINCT agent_name) as agents FROM tasks WHERE run_id = ?",
            (r["id"],)
        ).fetchone()
        row["tasks_completed"] = counts["tasks"] if counts else 0
        row["agents_involved"] = counts["agents"] if counts else 0
        result.append(row)
    conn.close()
    print(json.dumps(result, indent=2))


def cmd_clear(project_dir: str):
    """Clear all brain data for a project. Asks for confirmation via env var."""
    if os.environ.get("CLAUDE_BRAIN_CONFIRM_CLEAR") != "yes":
        print(json.dumps({
            "status": "aborted",
            "message": "Set CLAUDE_BRAIN_CONFIRM_CLEAR=yes to confirm"
        }))
        sys.exit(1)
    path = db_path(project_dir)
    if path.exists():
        path.unlink()
    print(json.dumps({"status": "cleared", "path": str(path)}))


def cmd_init_run(project_dir: str, session_id: str):
    """Create a new run entry at session start."""
    conn = get_conn(project_dir)
    run_id = session_id or uid()
    existing = conn.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO runs (id, project_dir, session_id, started_at) VALUES (?,?,?,?)",
            (run_id, project_dir, session_id, ts())
        )
        conn.commit()
    conn.close()
    print(json.dumps({"status": "ok", "run_id": run_id}))


def cmd_kb_index(args):
    """Index content into the knowledge base."""
    project_dir, source, content_file = args[0], args[1], args[2]
    with open(content_file, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()

    chunks = chunk_content(content, source)
    conn = get_conn(project_dir)
    session_id = os.environ.get('CLAUDE_SESSION_ID', '')

    inserted = 0
    total_bytes = 0
    for chunk in chunks:
        b = len(chunk['content'].encode('utf-8'))
        conn.execute(
            "INSERT INTO kb_chunks (session_id, source, title, content, bytes) VALUES (?,?,?,?,?)",
            (session_id, source, chunk['title'], chunk['content'], b)
        )
        total_bytes += b
        inserted += 1
    conn.commit()

    print(json.dumps({"source": source, "chunks": inserted, "bytes": total_bytes}))


def cmd_kb_search(args):
    """Search the knowledge base."""
    project_dir = args[0]
    query = args[1]
    limit = int(args[2]) if len(args) > 2 else 5

    conn = get_conn(project_dir)
    rows = kb_search_query(conn, query, limit)

    results = []
    for title, content, source in rows:
        snippet = extract_snippet(content, query, max_len=800)
        results.append({"title": title, "source": source, "snippet": snippet})

    print(json.dumps(results))


def cmd_kb_stats(args):
    """Show knowledge base statistics."""
    project_dir = args[0]
    conn = get_conn(project_dir)
    row = conn.execute("SELECT COUNT(*), COALESCE(SUM(bytes),0), COUNT(DISTINCT source) FROM kb_chunks").fetchone()
    print(json.dumps({"chunks": row[0], "bytes_indexed": row[1], "sources": row[2]}))


# ── Entrypoint ────────────────────────────────────────────────────────────────

def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)

    cmd = args[0]
    cwd = os.environ.get("CLAUDE_PROJECT_DIR", os.getcwd())

    try:
        if cmd == "init":
            cmd_init(args[1] if len(args) > 1 else cwd)

        elif cmd == "init-run":
            project_dir = args[1] if len(args) > 1 else cwd
            session_id = args[2] if len(args) > 2 else ""
            cmd_init_run(project_dir, session_id)

        elif cmd == "index-task":
            payload = args[1] if len(args) > 1 else sys.stdin.read()
            cmd_index_task(payload)

        elif cmd == "query-role":
            role = args[1] if len(args) > 1 else "general"
            project_dir = args[2] if len(args) > 2 else cwd
            cmd_query_role(role, project_dir)

        elif cmd == "status":
            project_dir = args[1] if len(args) > 1 else cwd
            cmd_status(project_dir)

        elif cmd == "summarize-run":
            run_id = args[1] if len(args) > 1 else ""
            project_dir = args[2] if len(args) > 2 else cwd
            cmd_summarize_run(run_id, project_dir)

        elif cmd == "list-runs":
            project_dir = args[1] if len(args) > 1 else cwd
            cmd_list_runs(project_dir)

        elif cmd == "clear":
            project_dir = args[1] if len(args) > 1 else cwd
            cmd_clear(project_dir)

        elif cmd == "kb-index":
            cmd_kb_index(args[1:])

        elif cmd == "kb-search":
            cmd_kb_search(args[1:])

        elif cmd == "kb-stats":
            cmd_kb_stats(args[1:])

        else:
            print(f"Unknown command: {cmd}", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
