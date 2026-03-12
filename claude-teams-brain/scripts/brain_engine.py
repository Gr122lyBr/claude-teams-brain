#!/usr/bin/env python3
"""
claude-brain engine
Persistent memory store for Claude Code Agent Teams.
Uses only Python stdlib — no external dependencies.

Usage:
  brain_engine.py init <project_dir>
  brain_engine.py init-run <project_dir> [<session_id>]
  brain_engine.py index-task <json>
  brain_engine.py query-role <role> [<project_dir>] [<task_description>]
  brain_engine.py status [<project_dir>]
  brain_engine.py summarize-run <run_id> [<project_dir>]
  brain_engine.py list-runs [<project_dir>]
  brain_engine.py list-tasks [<project_dir>] [<limit>]
  brain_engine.py clear [<project_dir>]
  brain_engine.py remember <text> [<project_dir>]
  brain_engine.py forget <text> [<project_dir>]
  brain_engine.py export-conventions [<project_dir>]
  brain_engine.py kb-index <project_dir> <source> <content_file>
  brain_engine.py kb-search <project_dir> <query> [<limit>]
  brain_engine.py kb-stats <project_dir>
  brain_engine.py replay-run <run_id_or_latest> [<project_dir>]
  brain_engine.py seed-profile <profile_name_or_path> [<project_dir>]
  brain_engine.py list-profiles
  brain_engine.py role-stats [<project_dir>]
  brain_engine.py full-stats [<project_dir>]
  brain_engine.py decision-timeline [<project_dir>]
  brain_engine.py learn [<project_dir>]
  brain_engine.py kb-source-age <project_dir> <source>
"""

import sys
import os
import json
import sqlite3
import hashlib
import re
import time
import subprocess
from collections import defaultdict
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

CREATE TRIGGER IF NOT EXISTS kb_fts_delete AFTER DELETE ON kb_chunks BEGIN
    DELETE FROM kb_fts WHERE rowid = old.id;
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

CREATE TRIGGER IF NOT EXISTS tasks_fts_delete AFTER DELETE ON tasks BEGIN
    DELETE FROM tasks_fts WHERE rowid = old.rowid;
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

CREATE TRIGGER IF NOT EXISTS tasks_fts_trigram_delete AFTER DELETE ON tasks BEGIN
    DELETE FROM tasks_fts_trigram WHERE rowid = old.rowid;
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
        conn.execute("""CREATE TRIGGER IF NOT EXISTS kb_fts_trigram_delete AFTER DELETE ON kb_chunks BEGIN
            DELETE FROM kb_fts_trigram WHERE rowid = old.id;
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
        total += len(chunk) + len(prefix) + len(suffix)

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
            "SELECT kc.title, kc.content, kc.source FROM kb_fts kf JOIN kb_chunks kc ON kf.chunk_id = kc.id WHERE kb_fts MATCH ? ORDER BY rank LIMIT ?",
            (query, limit)
        ).fetchall()
        if rows:
            return rows
    except Exception:
        pass

    # Layer 2: Trigram
    try:
        rows = conn.execute(
            "SELECT kc.title, kc.content, kc.source FROM kb_fts_trigram kf JOIN kb_chunks kc ON kf.chunk_id = kc.id WHERE kb_fts_trigram MATCH ? ORDER BY rank LIMIT ?",
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
                "SELECT kc.title, kc.content, kc.source FROM kb_fts kf JOIN kb_chunks kc ON kf.chunk_id = kc.id WHERE kb_fts MATCH ? ORDER BY rank LIMIT ?",
                (word, limit)
            ).fetchall()
            for row in rows:
                if row[1] not in seen:
                    seen.add(row[1])
                    results.append(row)
        except Exception:
            pass
    return results[:limit]


def score_relevance(text: str, keywords: list, completed_at: str = '') -> int:
    """Score a text by keyword matches (word-boundary aware) with recency boost."""
    if not keywords or not text:
        return 0
    t = text.lower()
    score = 0
    for kw in keywords:
        try:
            if re.search(r'\b' + re.escape(kw) + r'\b', t):
                score += 1
        except re.error:
            if kw in t:
                score += 1

    # Recency boost: +2 for last 7 days, +1 for last 30 days
    if completed_at:
        try:
            from datetime import datetime, timezone, timedelta
            dt = datetime.fromisoformat(completed_at.replace('Z', '+00:00'))
            now = datetime.now(timezone.utc)
            age = (now - dt).days
            if age <= 7:
                score += 2
            elif age <= 30:
                score += 1
        except Exception:
            pass
    return score


# Decision type classification keywords
DECISION_TYPE_KEYWORDS = {
    'architecture': ['architect', 'structure', 'pattern', 'monolith', 'microservice', 'layer', 'module', 'design', 'separation', 'coupling'],
    'dependency':   ['install', 'package', 'library', 'framework', 'version', 'upgrade', 'npm', 'pip', 'dependency', 'import'],
    'convention':   ['convention', 'standard', 'rule', 'naming', 'format', 'style', 'lint', 'always', 'never', 'must'],
    'pattern':      ['pattern', 'approach', 'strategy', 'factory', 'singleton', 'hook', 'middleware', 'handler', 'service'],
    'tooling':      ['tool', 'script', 'build', 'test runner', 'ci', 'docker', 'webpack', 'vite', 'jest', 'deploy'],
}


def tag_decision_type(text: str) -> str:
    """Return the most likely decision type tag."""
    t = text.lower()
    scores = {}
    for dtype, keywords in DECISION_TYPE_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in t)
        if score > 0:
            scores[dtype] = score
    return max(scores, key=scores.get) if scores else 'general'


# Word pairs that signal contradictions
CONFLICT_PAIRS = [
    ({'use', 'using', 'chose', 'prefer', 'adopt'}, {'avoid', 'never', 'remove', 'replace', 'drop', 'migrate away'}),
]


def detect_conflicts(conn, new_decisions: list, agent_role: str) -> list:
    """Check new decisions against stored ones for potential contradictions."""
    if not new_decisions:
        return []
    conflicts = []
    try:
        existing = conn.execute(
            "SELECT decisions FROM tasks WHERE agent_role != '' ORDER BY completed_at DESC LIMIT 50"
        ).fetchall()
        existing_texts = []
        for row in existing:
            try:
                existing_texts.extend(json.loads(row['decisions'] or '[]'))
            except Exception:
                pass

        for new_dec in new_decisions:
            new_lower = new_dec.lower()
            # Extract tech/topic words (nouns, capitalized, or after "use/prefer/avoid")
            new_topics = set(re.findall(r'\b[A-Z][a-z]+\b|\b[a-z]{4,}\b', new_dec))
            for existing_dec in existing_texts:
                ex_lower = existing_dec.lower()
                ex_topics = set(re.findall(r'\b[A-Z][a-z]+\b|\b[a-z]{4,}\b', existing_dec))
                shared = new_topics & ex_topics
                if len(shared) >= 2:
                    # Check for opposite sentiment
                    new_positive = any(w in new_lower for w in ['use', 'using', 'chose', 'prefer', 'adopt', 'switch to'])
                    new_negative = any(w in new_lower for w in ['avoid', 'never', 'remove', 'replace', 'drop'])
                    ex_positive = any(w in ex_lower for w in ['use', 'using', 'chose', 'prefer', 'adopt', 'switch to'])
                    ex_negative = any(w in ex_lower for w in ['avoid', 'never', 'remove', 'replace', 'drop'])
                    if (new_positive and ex_negative) or (new_negative and ex_positive):
                        conflicts.append(f"\u26a0\ufe0f Possible conflict: '{new_dec[:80]}' vs '{existing_dec[:80]}'")
    except Exception:
        pass
    return conflicts[:3]  # Cap at 3 warnings


def summarize_large_content(content: str, max_bytes: int = 8000) -> str:
    """Extract the most important lines from large command output to keep KB lean."""
    if len(content.encode('utf-8')) <= max_bytes:
        return content

    lines = content.split('\n')
    important = []
    seen = set()

    IMPORTANT = re.compile(
        r'error|fail|warn|exception|traceback|pass|success|'
        r'✓|✗|×|\d+\s+(passing|failing|pending)|'
        r'^\s*at\s|^\s*File\s"',
        re.IGNORECASE
    )

    # First 20 lines (headers/config)
    for line in lines[:20]:
        if line.strip() and line not in seen:
            seen.add(line)
            important.append(line)

    # Important lines from the middle
    for line in lines[20:max(20, len(lines) - 30)]:
        if line.strip() and IMPORTANT.search(line) and line not in seen:
            seen.add(line)
            important.append(line)

    # Last 30 lines (summaries/totals)
    for line in lines[-30:]:
        if line.strip() and line not in seen:
            seen.add(line)
            important.append(line)

    result = '\n'.join(important)
    encoded = result.encode('utf-8')
    if len(encoded) > max_bytes:
        # Slice bytes then decode safely to avoid splitting multibyte chars
        result = encoded[:max_bytes].decode('utf-8', errors='ignore') + '\n...[summarized]'
    return result


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
    raw_decisions = p.get("decisions", [])
    tagged_decisions = [
        f"[{tag_decision_type(d)}] {d}" if not d.startswith('[') else d
        for d in raw_decisions
    ]
    decisions = json.dumps(tagged_decisions)

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

    # Detect conflicts with existing decisions
    conflict_warnings = detect_conflicts(conn, p.get("decisions", []), p.get("agent_role", ""))

    conn.close()
    result = {"status": "ok", "task_id": task_id}
    if conflict_warnings:
        result["conflicts"] = conflict_warnings
    print(json.dumps(result))


def cmd_query_role(role: str, project_dir: str, task_description: str = ""):
    """
    Return memory relevant to a role, ranked by relevance to the current task.
    Used by SubagentStart to inject context into a new teammate.
    Output is a formatted string ready to inject as additionalContext.
    """
    conn = get_conn(project_dir)
    role_lower = role.lower()

    # Build keyword set from task description for relevance scoring
    task_keywords = [w.lower() for w in re.split(r'\W+', task_description) if len(w) > 3] if task_description else []

    # Recent tasks for this role (fetch more, then rank by relevance)
    role_tasks = conn.execute(
        """SELECT t.task_subject, t.output_summary, t.files_touched, t.decisions,
                  t.completed_at, t.run_id
           FROM tasks t
           WHERE lower(t.agent_role) LIKE ? OR lower(t.agent_name) LIKE ?
           ORDER BY t.completed_at DESC LIMIT 20""",
        (f"%{role_lower}%", f"%{role_lower}%")
    ).fetchall()

    if task_keywords:
        role_tasks = sorted(
            role_tasks,
            key=lambda t: score_relevance(
                (t["task_subject"] or "") + " " + (t["output_summary"] or ""),
                task_keywords,
                t["completed_at"] or ''
            ),
            reverse=True
        )

    fts_results = search_with_fallback(conn, role, limit=5)

    # Manual memories (user-defined rules — always injected)
    manual_memories = conn.execute(
        """SELECT decision FROM decisions
           WHERE agent_name = 'user' ORDER BY created_at DESC"""
    ).fetchall()

    # Team decisions — deduplicated and relevance-ranked
    raw_decisions = conn.execute(
        """SELECT d.decision, d.rationale, d.agent_name, d.created_at
           FROM decisions d WHERE d.agent_name != 'user'
           ORDER BY d.created_at DESC LIMIT 30"""
    ).fetchall()

    seen_dec = set()
    all_decisions = []
    for d in raw_decisions:
        key = d["decision"].strip().lower()[:100]
        if key not in seen_dec:
            seen_dec.add(key)
            all_decisions.append(d)

    if task_keywords:
        all_decisions = sorted(
            all_decisions,
            key=lambda d: score_relevance(
                (d["decision"] or "") + " " + (d["rationale"] or ""),
                task_keywords
            ),
            reverse=True
        )

    # Files this role has touched — deduplicated
    raw_files = conn.execute(
        """SELECT DISTINCT fi.file_path, fi.summary
           FROM file_index fi
           WHERE lower(fi.agent_name) LIKE ?
           ORDER BY fi.touched_at DESC LIMIT 30""",
        (f"%{role_lower}%",)
    ).fetchall()

    seen_files = set()
    role_files = []
    for f in raw_files:
        if f["file_path"] not in seen_files:
            seen_files.add(f["file_path"])
            role_files.append(f)

    last_run = conn.execute(
        "SELECT summary, started_at FROM runs ORDER BY started_at DESC LIMIT 1"
    ).fetchone()

    conn.close()

    if not role_tasks and not all_decisions and not fts_results and not manual_memories:
        print(json.dumps({"additionalContext": ""}))
        return

    lines = [
        f"## 🧠 claude-brain: Memory for role [{role}]",
        "_Auto-injected context from past Agent Team sessions_",
        "",
    ]

    if manual_memories:
        lines.append("### Project Rules & Conventions")
        lines.append("_Always follow these — set manually by the team:_")
        for m in manual_memories:
            lines.append(f"- {m['decision']}")
        lines.append("")

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
    if len(context) > CONTEXT_BUDGET:
        # Truncate at the last newline before the budget to avoid cutting mid-line
        cutoff = context.rfind('\n', 0, CONTEXT_BUDGET)
        if cutoff == -1:
            cutoff = CONTEXT_BUDGET
        context = context[:cutoff] + "\n\n_[Truncated — context budget of {} chars reached]_".format(CONTEXT_BUDGET)

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

    # Summarize large content before indexing to keep the KB lean
    content = summarize_large_content(content)

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
    conn.close()

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

    conn.close()
    print(json.dumps(results))


def cmd_kb_stats(args):
    """Show knowledge base statistics."""
    project_dir = args[0]
    conn = get_conn(project_dir)
    row = conn.execute("SELECT COUNT(*), COALESCE(SUM(bytes),0), COUNT(DISTINCT source) FROM kb_chunks").fetchone()
    conn.close()
    print(json.dumps({"chunks": row[0], "bytes_indexed": row[1], "sources": row[2]}))


def cmd_remember(text: str, project_dir: str):
    """Store a manual memory (rule/convention) that gets injected into all future teammates."""
    if not text.strip():
        print(json.dumps({"status": "error", "message": "Memory text cannot be empty"}))
        sys.exit(1)

    conn = get_conn(project_dir)

    # Use a stable synthetic run for all manual memories
    manual_run_id = 'manual-memories'
    existing = conn.execute("SELECT id FROM runs WHERE id = ?", (manual_run_id,)).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO runs (id, project_dir, session_id, started_at) VALUES (?,?,?,?)",
            (manual_run_id, project_dir, 'manual', ts())
        )

    conn.execute(
        """INSERT INTO decisions (id, run_id, agent_name, decision, rationale, tags, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (uid(), manual_run_id, 'user', text.strip(), '', json.dumps(['manual']), ts())
    )
    conn.commit()

    total = conn.execute(
        "SELECT COUNT(*) FROM decisions WHERE agent_name = 'user'"
    ).fetchone()[0]
    conn.close()

    print(json.dumps({"status": "ok", "memory": text.strip(), "total_manual": total}))


def cmd_forget(text: str, project_dir: str):
    """Remove a manual memory by matching text (partial match supported)."""
    conn = get_conn(project_dir)

    matches = conn.execute(
        "SELECT id, decision FROM decisions WHERE agent_name = 'user' AND lower(decision) LIKE ?",
        (f"%{text.lower()}%",)
    ).fetchall()

    if not matches:
        conn.close()
        print(json.dumps({"status": "not_found", "message": f"No manual memory matching: {text}"}))
        return

    for m in matches:
        conn.execute("DELETE FROM decisions WHERE id = ?", (m["id"],))
    conn.commit()
    conn.close()

    removed = [m["decision"] for m in matches]
    print(json.dumps({"status": "ok", "removed": removed}))


def cmd_export_conventions(project_dir: str):
    """Export accumulated brain knowledge as a CONVENTIONS.md content string."""
    conn = get_conn(project_dir)

    manual = conn.execute(
        "SELECT decision FROM decisions WHERE agent_name = 'user' ORDER BY created_at DESC"
    ).fetchall()

    team_decisions = conn.execute(
        """SELECT decision, rationale, agent_name FROM decisions
           WHERE agent_name != 'user' ORDER BY created_at DESC LIMIT 30"""
    ).fetchall()

    files = conn.execute(
        """SELECT file_path, COUNT(*) as touches, GROUP_CONCAT(DISTINCT agent_name) as agents
           FROM file_index GROUP BY file_path ORDER BY touches DESC LIMIT 20"""
    ).fetchall()

    agents = conn.execute(
        """SELECT DISTINCT agent_name, agent_role FROM tasks
           WHERE agent_name != '' ORDER BY completed_at DESC LIMIT 10"""
    ).fetchall()

    conn.close()

    lines = [
        "# Project Conventions",
        "",
        "_Auto-generated by claude-teams-brain from accumulated Agent Team memory._",
        "_Commit this file to share conventions with the whole team._",
        "",
    ]

    if manual:
        lines += ["## Rules & Conventions", ""]
        for m in manual:
            lines.append(f"- {m['decision']}")
        lines.append("")

    if team_decisions:
        lines += ["## Architectural Decisions", ""]
        for d in team_decisions[:20]:
            by = d["agent_name"] or "team"
            lines.append(f"- **[{by}]** {d['decision']}")
            if d["rationale"]:
                lines.append(f"  _{d['rationale']}_")
        lines.append("")

    if files:
        lines += ["## Key Files", ""]
        for f in files:
            agents_str = f["agents"] or ""
            lines.append(f"- `{f['file_path']}` — {f['touches']} edit(s) by {agents_str}")
        lines.append("")

    if agents:
        lines += ["## Agent Roles", ""]
        seen = set()
        for a in agents:
            name = a["agent_name"]
            if name not in seen:
                seen.add(name)
                role = a["agent_role"] or name
                lines.append(f"- **{name}**: {role}")
        lines.append("")

    content = "\n".join(lines)
    print(json.dumps({
        "status": "ok",
        "content": content,
        "rules_count": len(manual),
        "decisions_count": len(team_decisions),
        "files_count": len(files),
    }))


# ── New commands: replay-run, seed-profile, list-profiles ─────────────────────

def cmd_replay_run(run_id_arg: str, project_dir: str):
    """
    Generate a chronological narrative of what happened in a past run.
    Accepts a full run ID, a prefix, or the special values 'latest'/'last'.
    """
    conn = get_conn(project_dir)

    # Resolve run ID
    run = None
    if run_id_arg.lower() in ("latest", "last", ""):
        run = conn.execute(
            "SELECT id, started_at, ended_at, summary FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
    else:
        run = conn.execute(
            "SELECT id, started_at, ended_at, summary FROM runs WHERE id = ? OR id LIKE ? ORDER BY started_at DESC LIMIT 1",
            (run_id_arg, f"{run_id_arg}%")
        ).fetchone()

    if not run:
        conn.close()
        print(json.dumps({"status": "not_found", "message": f"Run '{run_id_arg}' not found. Use list-runs to see available sessions."}))
        sys.exit(1)

    run_id = run["id"]

    tasks = conn.execute(
        "SELECT task_subject, agent_name, agent_role, files_touched, decisions, output_summary, completed_at FROM tasks WHERE run_id = ? ORDER BY completed_at",
        (run_id,)
    ).fetchall()

    all_decisions = conn.execute(
        "SELECT decision, rationale, agent_name, created_at FROM decisions WHERE run_id = ? AND agent_name != 'user' ORDER BY created_at",
        (run_id,)
    ).fetchall()

    files = conn.execute(
        "SELECT file_path, operation, agent_name FROM file_index WHERE run_id = ? ORDER BY touched_at",
        (run_id,)
    ).fetchall()

    conn.close()

    started = (run["started_at"] or "")[:19].replace("T", " ")
    ended = (run["ended_at"] or "in progress")[:19].replace("T", " ")

    lines = [
        f"# Session Replay: `{run_id[:12]}`",
        f"**Started:** {started}  **Ended:** {ended}",
        "",
    ]

    if tasks:
        agents = list(dict.fromkeys(t["agent_name"] for t in tasks if t["agent_name"]))
        mode = "Team: " + ", ".join(agents) if agents else "Solo session"
        lines += [
            f"**{mode}**  |  **Tasks completed:** {len(tasks)}",
            "",
            "## Timeline",
            "",
        ]
        for i, t in enumerate(tasks, 1):
            agent = t["agent_name"] or "main"
            subj = t["task_subject"] or "(untitled)"
            time_str = (t["completed_at"] or "")[:19].replace("T", " ")

            lines.append(f"### {i}. [{agent}] {subj}")
            if time_str:
                lines.append(f"_Completed: {time_str}_")

            task_files = json.loads(t["files_touched"] or "[]")
            if task_files:
                suffix = " ..." if len(task_files) > 5 else ""
                lines.append(f"**Files:** {', '.join(f'`{f}`' for f in task_files[:5])}{suffix}")

            task_decisions = json.loads(t["decisions"] or "[]")
            if task_decisions:
                lines.append("**Decisions:**")
                for d in task_decisions[:3]:
                    d_str = d if isinstance(d, str) else d.get("decision", str(d))
                    lines.append(f"  - {d_str[:150]}")

            if t["output_summary"]:
                lines.append(f"**Summary:** {t['output_summary'][:250]}")

            lines.append("")

    if all_decisions:
        lines += ["## All Decisions", ""]
        for d in all_decisions:
            by = d["agent_name"] or "team"
            lines.append(f"- **[{by}]** {d['decision'][:200]}")
            if d["rationale"]:
                lines.append(f"  _{d['rationale'][:150]}_")
        lines.append("")

    if files:
        lines += ["## Files Touched", ""]
        seen: dict = {}
        for f in files:
            fp = f["file_path"]
            if fp not in seen:
                seen[fp] = set()
            if f["agent_name"]:
                seen[fp].add(f["agent_name"])
        for fp, agents_set in list(seen.items())[:25]:
            agents_str = ", ".join(sorted(agents_set)) if agents_set else "unknown"
            lines.append(f"- `{fp}` — {agents_str}")
        lines.append("")

    if run["summary"]:
        lines += ["## Session Summary", "", run["summary"], ""]

    narrative = "\n".join(lines)
    print(json.dumps({"status": "ok", "run_id": run_id, "narrative": narrative}))


def cmd_seed_profile(profile_arg: str, project_dir: str):
    """
    Seed the brain with conventions from a named stack profile.
    Built-in profiles live in the `profiles/` dir next to the plugin root.
    Accepts a profile name, fuzzy match, or path to a custom JSON file.
    """
    if not profile_arg.strip():
        print(json.dumps({"status": "error", "message": "Profile name required. Use list-profiles to see available profiles."}))
        sys.exit(1)

    profiles_dir = Path(__file__).parent.parent / "profiles"
    profile_path = None

    # 1. Exact filename match (with or without .json)
    for ext in ("", ".json"):
        candidate = profiles_dir / f"{profile_arg}{ext}"
        if candidate.exists():
            profile_path = candidate
            break

    # 2. Fuzzy match (e.g. "nextjs" matches "nextjs-prisma.json")
    if not profile_path and profiles_dir.exists():
        for f in sorted(profiles_dir.glob("*.json")):
            if profile_arg.lower() in f.stem.lower():
                profile_path = f
                break

    # 3. Treat as raw file path
    if not profile_path:
        custom = Path(profile_arg)
        if custom.exists():
            profile_path = custom

    if not profile_path:
        available = [f.stem for f in sorted(profiles_dir.glob("*.json"))] if profiles_dir.exists() else []
        print(json.dumps({
            "status": "not_found",
            "message": f"Profile '{profile_arg}' not found.",
            "available": available,
        }))
        sys.exit(1)

    with open(profile_path, encoding="utf-8") as f:
        profile = json.load(f)

    conventions = profile.get("conventions", [])
    profile_name = profile.get("name", profile_path.stem)

    conn = get_conn(project_dir)
    manual_run_id = "manual-memories"
    existing = conn.execute("SELECT id FROM runs WHERE id = ?", (manual_run_id,)).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO runs (id, project_dir, session_id, started_at) VALUES (?,?,?,?)",
            (manual_run_id, project_dir, "manual", ts())
        )

    added = 0
    for convention in conventions:
        if not str(convention).strip():
            continue
        conn.execute(
            """INSERT INTO decisions (id, run_id, agent_name, decision, rationale, tags, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (uid(), manual_run_id, "user", str(convention).strip(),
             f"From profile: {profile_name}",
             json.dumps(["profile", profile_path.stem]), ts())
        )
        added += 1

    conn.commit()
    conn.close()

    print(json.dumps({
        "status": "ok",
        "profile": profile_name,
        "conventions_added": added,
        "message": f"Seeded {added} conventions from '{profile_name}' profile. They will be injected into all future teammates.",
    }))


def cmd_list_profiles():
    """List all available built-in stack profiles."""
    profiles_dir = Path(__file__).parent.parent / "profiles"
    profiles = []

    if profiles_dir.exists():
        for f in sorted(profiles_dir.glob("*.json")):
            try:
                with open(f, encoding="utf-8") as fp:
                    p = json.load(fp)
                profiles.append({
                    "id": f.stem,
                    "name": p.get("name", f.stem),
                    "description": p.get("description", ""),
                    "stack": p.get("stack", []),
                    "conventions_count": len(p.get("conventions", [])),
                })
            except Exception:
                pass

    print(json.dumps(profiles, indent=2))


def cmd_list_tasks(project_dir: str, limit: int = 5):
    """List most recent tasks as JSON."""
    conn = get_conn(project_dir)
    rows = conn.execute(
        "SELECT task_subject, agent_name, agent_role, output_summary, completed_at "
        "FROM tasks ORDER BY completed_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    tasks = []
    for r in rows:
        tasks.append({
            "subject": r["task_subject"],
            "agent": r["agent_name"] or r["agent_role"] or "",
            "summary": (r["output_summary"] or "")[:200],
            "completed": r["completed_at"],
        })
    print(json.dumps(tasks, indent=2))


def cmd_decision_timeline(project_dir: str):
    """Print all decisions chronologically, grouped by role."""
    conn = get_conn(project_dir)
    rows = conn.execute(
        """SELECT t.agent_role, t.decisions, t.completed_at, t.task_subject
           FROM tasks t
           WHERE t.decisions != '[]' AND t.decisions IS NOT NULL
           ORDER BY t.completed_at ASC"""
    ).fetchall()
    conn.close()

    lines = ["# Decision Timeline\n"]
    for row in rows:
        try:
            decs = json.loads(row['decisions'] or '[]')
        except Exception:
            continue
        if not decs:
            continue
        ts_str = (row['completed_at'] or '')[:10]
        role = row['agent_role'] or 'unknown'
        lines.append(f"## [{ts_str}] {role} — {(row['task_subject'] or '')[:60]}")
        for d in decs:
            lines.append(f"- {d}")
        lines.append("")
    print(json.dumps({"timeline": "\n".join(lines)}))


def cmd_role_stats(project_dir: str):
    """Print per-role stats as JSON."""
    conn = get_conn(project_dir)
    rows = conn.execute(
        """SELECT agent_role,
                  COUNT(DISTINCT t.id)         AS task_count,
                  COUNT(DISTINCT fi.file_path)  AS file_count,
                  MAX(t.completed_at)           AS last_active
           FROM tasks t
           LEFT JOIN file_index fi ON fi.task_id = t.id
           WHERE agent_role != ''
           GROUP BY agent_role
           ORDER BY task_count DESC"""
    ).fetchall()
    conn.close()
    result = [
        {
            "role": r["agent_role"],
            "tasks": r["task_count"],
            "files": r["file_count"],
            "last_active": r["last_active"],
        }
        for r in rows
    ]
    print(json.dumps(result))


def cmd_full_stats(project_dir: str):
    """Return combined stats (status + kb-stats + role-stats) in one call."""
    conn = get_conn(project_dir)

    # Status
    status = {
        "project_id": project_id(project_dir),
        "db_path": str(db_path(project_dir)),
        "runs": conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
        "tasks": conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0],
        "decisions": conn.execute("SELECT COUNT(*) FROM decisions").fetchone()[0],
        "files_indexed": conn.execute("SELECT COUNT(DISTINCT file_path) FROM file_index").fetchone()[0],
        "agents_seen": conn.execute("SELECT COUNT(DISTINCT agent_name) FROM tasks WHERE agent_name != ''").fetchone()[0],
        "last_activity": conn.execute("SELECT MAX(completed_at) FROM tasks").fetchone()[0],
    }

    # KB stats
    kb_row = conn.execute("SELECT COUNT(*), COALESCE(SUM(bytes),0), COUNT(DISTINCT source) FROM kb_chunks").fetchone()
    kb = {"chunks": kb_row[0], "bytes_indexed": kb_row[1], "sources": kb_row[2]}

    # Role stats
    role_rows = conn.execute(
        """SELECT agent_role,
                  COUNT(DISTINCT t.id)         AS task_count,
                  COUNT(DISTINCT fi.file_path)  AS file_count,
                  MAX(t.completed_at)           AS last_active
           FROM tasks t
           LEFT JOIN file_index fi ON fi.task_id = t.id
           WHERE agent_role != ''
           GROUP BY agent_role
           ORDER BY task_count DESC"""
    ).fetchall()
    roles = [
        {"role": r["agent_role"], "tasks": r["task_count"], "files": r["file_count"], "last_active": r["last_active"]}
        for r in role_rows
    ]

    conn.close()
    print(json.dumps({"status": status, "kb": kb, "roles": roles}, indent=2))


def cmd_kb_source_age(args):
    """Return hours since a KB source was last indexed. -1 if never."""
    project_dir, source = args[0], args[1]
    conn = get_conn(project_dir)
    row = conn.execute(
        "SELECT MAX(indexed_at) FROM kb_chunks WHERE source = ?", (source,)
    ).fetchone()
    conn.close()
    last = row[0] if row and row[0] else None
    if not last:
        print(json.dumps({"hours_ago": -1}))
        return
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(last.replace('Z', '+00:00'))
        now = datetime.now(timezone.utc)
        hours = (now - dt).total_seconds() / 3600
        print(json.dumps({"hours_ago": round(hours, 1)}))
    except Exception:
        print(json.dumps({"hours_ago": -1}))


# ── Git Learn ─────────────────────────────────────────────────────────────────


def _learn_run_git(args_list, project_dir, timeout=30):
    """Run a git command and return stdout, or empty string on failure."""
    try:
        result = subprocess.run(
            ["git", "-C", project_dir] + args_list,
            capture_output=True, text=True, timeout=timeout
        )
        return result.stdout if result.returncode == 0 else ""
    except Exception:
        return ""


def _learn_parse_git_log(raw_output):
    """Parse git log output with NUL-delimited commits and numstat."""
    if not raw_output.strip():
        return []

    commits = []
    # Split on NUL byte — each chunk is one commit
    chunks = raw_output.split('\x00')
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        lines = chunk.split('\n')
        header = lines[0]
        parts = header.split('\x01')
        if len(parts) < 5:
            continue

        commit_hash, author, subject, body, date = parts[0], parts[1], parts[2], parts[3], parts[4]

        files = []
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            # numstat format: added\tdeleted\tpath
            tab_parts = line.split('\t')
            if len(tab_parts) >= 3:
                path = tab_parts[2]
                # Handle renames: {old => new}
                if '=>' in path:
                    # Extract new path from rename notation
                    path = re.sub(r'\{[^}]*=> *([^}]*)\}', r'\1', path)
                    path = path.replace('//', '/')
                files.append(path)

        commits.append({
            "hash": commit_hash,
            "author": author,
            "subject": subject,
            "body": body,
            "date": date,
            "files": files,
        })

    return commits


def _learn_commit_conventions(commits):
    """Extract commit message conventions."""
    if not commits:
        return []

    conventions = []
    subjects = [c["subject"] for c in commits]
    total = len(subjects)

    # 1. Conventional commits
    cc_pattern = re.compile(r'^(feat|fix|chore|docs|style|refactor|perf|test|build|ci|revert)(\(.+?\))?(!)?:')
    cc_matches = [s for s in subjects if cc_pattern.match(s)]
    if len(cc_matches) > total * 0.4:
        # Extract common scopes
        scopes = []
        for s in cc_matches:
            m = re.match(r'^[a-z]+\((.+?)\)', s)
            if m:
                scopes.append(m.group(1))
        scope_info = ""
        if scopes:
            from collections import Counter
            top_scopes = [s for s, _ in Counter(scopes).most_common(3)]
            if top_scopes:
                scope_info = f" — common scopes: {', '.join(top_scopes)}"
        conventions.append(f"Convention: commit messages use Conventional Commits (type: description){scope_info}")

    # 2. Ticket prefixes
    ticket_pattern = re.compile(r'^[A-Z]{2,}-\d+|^\[.+?\]|#\d+')
    ticket_matches = [s for s in subjects if ticket_pattern.search(s)]
    if len(ticket_matches) > total * 0.25:
        # Find example prefix
        examples = set()
        for s in ticket_matches[:10]:
            m = re.match(r'^([A-Z]{2,})-\d+', s)
            if m:
                examples.add(m.group(1))
        ex = f" (e.g., {list(examples)[0]}-XXX)" if examples else ""
        conventions.append(f"Convention: commit messages reference tickets{ex}")

    # 3. Subject casing
    alpha_subjects = [s for s in subjects if s and s[0].isalpha()]
    if alpha_subjects:
        lowercase_ratio = sum(1 for s in alpha_subjects if s[0].islower()) / len(alpha_subjects)
        if lowercase_ratio > 0.7:
            conventions.append("Convention: commit subjects start with lowercase")
        elif lowercase_ratio < 0.2:
            conventions.append("Convention: commit subjects start with uppercase")

    # 4. Co-authors
    co_author_count = sum(1 for c in commits if 'Co-authored-by' in c.get("body", "") or 'Co-Authored-By' in c.get("body", ""))
    if co_author_count > total * 0.3:
        conventions.append("Convention: commits include Co-authored-by trailers")

    return conventions


def _learn_branch_conventions(project_dir):
    """Extract branch naming conventions."""
    raw = _learn_run_git(
        ["branch", "-r", "--format=%(refname:short)", "--sort=-committerdate"],
        project_dir, timeout=10
    )
    if not raw.strip():
        return []

    branches = [b.strip() for b in raw.strip().split('\n') if b.strip()][:50]
    # Strip remote prefix (origin/)
    names = [b.split('/', 1)[1] if '/' in b else b for b in branches]

    conventions = []
    prefixes = defaultdict(int)
    prefix_pattern = re.compile(r'^(feature|feat|fix|bugfix|hotfix|chore|release|develop|staging)[/-]')
    for name in names:
        m = prefix_pattern.match(name)
        if m:
            prefixes[m.group(1)] += 1

    total_prefixed = sum(prefixes.values())
    if total_prefixed > len(names) * 0.3 and total_prefixed >= 3:
        top = sorted(prefixes.keys())
        conventions.append(f"Convention: branches use prefix naming ({', '.join(p + '/' for p in top)})")

    return conventions


def _learn_architecture_signals(commits):
    """Extract architecture signals from file paths."""
    all_files = set()
    for c in commits:
        all_files.update(c["files"])

    if not all_files:
        return []

    signals = []

    # 1. Migration patterns
    migration_frameworks = {
        'alembic': 'Alembic (Python)',
        'migrations': 'database migrations',
        'flyway': 'Flyway',
        'liquibase': 'Liquibase',
        'knex': 'Knex.js',
        'prisma/migrations': 'Prisma',
    }
    for key, name in migration_frameworks.items():
        if any(key in f for f in all_files):
            signals.append(f"Architecture: uses {name}")
            break

    # 2. Test naming patterns
    test_patterns = {
        '.test.': '*.test.* naming',
        '.spec.': '*.spec.* naming',
        'test_': 'test_* naming',
        '_test.': '*_test.* naming',
    }
    test_counts = {k: sum(1 for f in all_files if k in f) for k in test_patterns}
    dominant = max(test_counts, key=test_counts.get) if test_counts else None
    if dominant and test_counts[dominant] >= 3:
        signals.append(f"Convention: tests use {test_patterns[dominant]}")

    # 3. Primary stack detection
    stack_markers = {
        'package.json': 'JavaScript/TypeScript (Node.js)',
        'requirements.txt': 'Python',
        'pyproject.toml': 'Python',
        'go.mod': 'Go',
        'Cargo.toml': 'Rust',
        'pom.xml': 'Java (Maven)',
        'build.gradle': 'Java/Kotlin (Gradle)',
        'Gemfile': 'Ruby',
        'composer.json': 'PHP',
    }
    for marker, stack in stack_markers.items():
        if any(f.endswith(marker) or f == marker for f in all_files):
            signals.append(f"Architecture: primary stack is {stack}")
            break

    # 4. CI/CD detection
    ci_markers = {
        '.github/workflows': 'GitHub Actions',
        '.gitlab-ci': 'GitLab CI',
        'Jenkinsfile': 'Jenkins',
        '.circleci': 'CircleCI',
        '.travis.yml': 'Travis CI',
    }
    for marker, name in ci_markers.items():
        if any(marker in f for f in all_files):
            signals.append(f"Architecture: CI/CD uses {name}")
            break

    # 5. Containerization
    if any('Dockerfile' in f or 'docker-compose' in f for f in all_files):
        signals.append("Architecture: uses Docker for containerization")

    # 6. Monorepo detection
    pkg_dirs = set()
    for f in all_files:
        if f.endswith('package.json'):
            pkg_dirs.add(os.path.dirname(f))
    if len(pkg_dirs) > 2:
        signals.append("Architecture: monorepo structure detected")

    return signals


def _learn_file_coupling(commits):
    """Find files that frequently change together."""
    pair_counts = defaultdict(int)

    for c in commits:
        files = sorted(set(c["files"]))
        # Skip mega-commits (likely auto-generated)
        if len(files) > 50 or len(files) < 2:
            continue
        for i in range(len(files)):
            for j in range(i + 1, len(files)):
                pair_counts[frozenset({files[i], files[j]})] += 1

    total = len(commits) or 1
    threshold = max(3, int(total * 0.05))
    coupled = [
        (pair, count)
        for pair, count in pair_counts.items()
        if count >= threshold
    ]
    coupled.sort(key=lambda x: -x[1])

    results = []
    for pair, count in coupled[:20]:
        a, b = sorted(pair)
        results.append({
            "file_a": a,
            "file_b": b,
            "co_occurrences": count,
            "pct": round(count / total * 100, 1),
        })
    return results


def _learn_hotspots(commits):
    """Find files and directories with the most changes."""
    file_counts = defaultdict(int)
    dir_counts = defaultdict(int)

    for c in commits:
        for f in c["files"]:
            file_counts[f] += 1
            top_dir = f.split('/')[0] if '/' in f else f
            dir_counts[top_dir] += 1

    results = []
    # Top 15 files
    for path, count in sorted(file_counts.items(), key=lambda x: -x[1])[:15]:
        results.append({"path": path, "commit_count": count, "type": "file"})
    # Top 8 directories
    for path, count in sorted(dir_counts.items(), key=lambda x: -x[1])[:8]:
        results.append({"path": path, "commit_count": count, "type": "directory"})

    return results


def _learn_deduplicate(conn, new_conventions):
    """Filter out conventions already stored in the brain."""
    existing = conn.execute(
        "SELECT decision FROM decisions WHERE agent_name = 'user'"
    ).fetchall()
    existing_set = {r["decision"].lower().strip() for r in existing}
    return [c for c in new_conventions if c.lower().strip() not in existing_set]


def cmd_learn(project_dir):
    """Auto-learn conventions from git history."""
    # Verify git repo
    check = _learn_run_git(["rev-parse", "--git-dir"], project_dir, timeout=5)
    if not check:
        print(json.dumps({"status": "error", "message": "Not a git repository"}))
        sys.exit(1)

    # Parse git log (last 200 commits)
    raw_log = _learn_run_git(
        ["log", "--pretty=format:%x00%H%x01%an%x01%s%x01%b%x01%aI", "--numstat", "-200"],
        project_dir, timeout=30
    )
    commits = _learn_parse_git_log(raw_log)
    if not commits:
        print(json.dumps({"status": "error", "message": "No commits found"}))
        sys.exit(1)

    # Run all analysis passes
    all_conventions = []
    all_conventions.extend(_learn_commit_conventions(commits))
    all_conventions.extend(_learn_branch_conventions(project_dir))
    all_conventions.extend(_learn_architecture_signals(commits))

    # File analysis
    couplings = _learn_file_coupling(commits)
    hotspots = _learn_hotspots(commits)

    # Deduplicate and store conventions
    conn = get_conn(project_dir)
    new_conventions = _learn_deduplicate(conn, all_conventions)
    skipped = len(all_conventions) - len(new_conventions)

    # Ensure a run exists for manual memories
    manual_run_id = 'manual-memories'
    existing = conn.execute("SELECT id FROM runs WHERE id = ?", (manual_run_id,)).fetchone()
    if not existing:
        conn.execute(
            "INSERT INTO runs (id, project_dir, session_id, started_at) VALUES (?,?,?,?)",
            (manual_run_id, project_dir, 'manual', ts())
        )

    # Store new conventions as decisions
    for conv in new_conventions:
        # Determine category tag
        cat = 'general'
        if conv.startswith('Architecture:'):
            cat = 'architecture'
        elif 'commit' in conv.lower():
            cat = 'commit'
        elif 'branch' in conv.lower():
            cat = 'branch'
        elif 'test' in conv.lower():
            cat = 'testing'

        conn.execute(
            """INSERT INTO decisions (id, run_id, agent_name, decision, rationale, tags, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            (uid(), manual_run_id, 'user', conv, 'Auto-learned from git history', json.dumps(['git-learn', cat]), ts())
        )

    # Store coupling data in KB (replace existing)
    conn.execute("DELETE FROM kb_chunks WHERE source = 'git-learn-coupling'")
    if couplings:
        coupling_text = "# File Coupling Analysis\n\nFiles that frequently change together:\n\n"
        for c in couplings:
            coupling_text += f"- {c['file_a']} <-> {c['file_b']} ({c['co_occurrences']} commits, {c['pct']}%)\n"
        content_bytes = coupling_text.encode('utf-8')
        conn.execute(
            "INSERT INTO kb_chunks (session_id, source, title, content, bytes, indexed_at) VALUES (?,?,?,?,?,?)",
            ('git-learn', 'git-learn-coupling', 'File Coupling Patterns', coupling_text, len(content_bytes), ts())
        )

    # Store hotspot data in KB (replace existing)
    conn.execute("DELETE FROM kb_chunks WHERE source = 'git-learn-hotspots'")
    if hotspots:
        file_spots = [h for h in hotspots if h["type"] == "file"]
        dir_spots = [h for h in hotspots if h["type"] == "directory"]
        hotspot_text = "# Code Hotspot Analysis\n\n## Most Changed Files\n\n"
        for h in file_spots:
            hotspot_text += f"- {h['path']} ({h['commit_count']} commits)\n"
        hotspot_text += "\n## Most Active Directories\n\n"
        for h in dir_spots:
            hotspot_text += f"- {h['path']}/ ({h['commit_count']} commits)\n"
        content_bytes = hotspot_text.encode('utf-8')
        conn.execute(
            "INSERT INTO kb_chunks (session_id, source, title, content, bytes, indexed_at) VALUES (?,?,?,?,?,?)",
            ('git-learn', 'git-learn-hotspots', 'Code Hotspot Analysis', hotspot_text, len(content_bytes), ts())
        )

    conn.commit()
    conn.close()

    print(json.dumps({
        "status": "ok",
        "commits_analyzed": len(commits),
        "conventions_found": len(all_conventions),
        "conventions_added": len(new_conventions),
        "conventions_skipped": skipped,
        "file_couplings": len(couplings),
        "hotspots": len(hotspots),
        "conventions": new_conventions,
        "message": f"Learned {len(new_conventions)} conventions from {len(commits)} commits."
    }, indent=2))


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
            task_desc = args[3] if len(args) > 3 else ""
            cmd_query_role(role, project_dir, task_desc)

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

        elif cmd == "remember":
            text = args[1] if len(args) > 1 else ""
            project_dir = args[2] if len(args) > 2 else cwd
            cmd_remember(text, project_dir)

        elif cmd == "forget":
            text = args[1] if len(args) > 1 else ""
            project_dir = args[2] if len(args) > 2 else cwd
            cmd_forget(text, project_dir)

        elif cmd == "export-conventions":
            project_dir = args[1] if len(args) > 1 else cwd
            cmd_export_conventions(project_dir)

        elif cmd == "kb-index":
            cmd_kb_index(args[1:])

        elif cmd == "kb-search":
            cmd_kb_search(args[1:])

        elif cmd == "kb-stats":
            cmd_kb_stats(args[1:])

        elif cmd == "replay-run":
            run_id_arg = args[1] if len(args) > 1 else "latest"
            project_dir = args[2] if len(args) > 2 else cwd
            cmd_replay_run(run_id_arg, project_dir)

        elif cmd == "seed-profile":
            profile_arg = args[1] if len(args) > 1 else ""
            project_dir = args[2] if len(args) > 2 else cwd
            cmd_seed_profile(profile_arg, project_dir)

        elif cmd == "list-profiles":
            cmd_list_profiles()

        elif cmd == "role-stats":
            cmd_role_stats(args[1] if len(args) > 1 else cwd)

        elif cmd == "full-stats":
            cmd_full_stats(args[1] if len(args) > 1 else cwd)

        elif cmd == "list-tasks":
            project_dir = args[1] if len(args) > 1 else cwd
            limit = int(args[2]) if len(args) > 2 else 5
            cmd_list_tasks(project_dir, limit)

        elif cmd == "decision-timeline":
            cmd_decision_timeline(args[1] if len(args) > 1 else cwd)

        elif cmd == "kb-source-age":
            cmd_kb_source_age(args[1:])

        elif cmd == "learn":
            cmd_learn(args[1] if len(args) > 1 else cwd)

        else:
            print(f"Unknown command: {cmd}", file=sys.stderr)
            sys.exit(1)

    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
