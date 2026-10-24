"""
Universal Memory Engine: Obsidian Vault + SQLite FTS5 Full-Text Indexing
Provides fast, lightweight, cross-agent memory with stale-commit detection.
"""

import os
import sys
import re
import json
import sqlite3
import subprocess
from datetime import datetime
from typing import List, Dict, Optional, Any

VAULT_ROOT = os.environ.get("UNIVERSAL_MEMORY_VAULT")
if not VAULT_ROOT:
    default_vault = os.path.expanduser(r"C:\Users\Halil Emre\Desktop\GitHub\obsidian")
    if os.path.exists(default_vault):
        VAULT_ROOT = default_vault
    else:
        VAULT_ROOT = os.path.expanduser("~/obsidian")

INDEX_DIR = os.path.join(VAULT_ROOT, ".index")
DB_PATH = os.path.join(INDEX_DIR, "memory.sqlite")

PROJECT_PATHS: Dict[str, str] = {
    "GrandStrategy3D": r"C:\Users\Halil Emre\Desktop\GitHub\Public\GrandStrategy3D",
    "GravityGuard": r"C:\Users\Halil Emre\Desktop\GitHub\Public\GravityGuard",
    "ClaudeVideoEditor": r"C:\Users\Halil Emre\Desktop\GitHub\Public\ClaudeVideoEditor",
    "Token-Lens": r"C:\Users\Halil Emre\.gemini\mcp\token-lens",
}


def _get_git_commit(project_name: str) -> Optional[str]:
    """Get current HEAD commit hash for a project if available."""
    repo_path = PROJECT_PATHS.get(project_name)
    if not repo_path or not (os.path.isdir(os.path.join(repo_path, ".git")) or os.path.isfile(os.path.join(repo_path, ".git"))):
        return None
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_path,
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        return out
    except Exception:
        return None


def check_validity(project_name: str, source_commit: str, applies_to: List[str] = []) -> Dict[str, Any]:
    """Inspect Git validity: valid, review_required, unknown, or diverged with file-level granularity."""
    if not source_commit or not project_name:
        return {"status": "unknown", "reason": "No source commit or project"}

    repo_path = PROJECT_PATHS.get(project_name)
    if not repo_path or not (os.path.isdir(os.path.join(repo_path, ".git")) or os.path.isfile(os.path.join(repo_path, ".git"))):
        return {"status": "unknown", "reason": f"No git repository found for project '{project_name}'"}

    head_commit = _get_git_commit(project_name)
    if not head_commit:
        return {"status": "unknown", "reason": "Could not determine HEAD commit"}

    if head_commit == source_commit:
        return {"status": "valid", "head_commit": head_commit, "source_commit": source_commit}

    # If applies_to is specified, check if those exact files changed since source_commit
    if applies_to:
        try:
            diff_cmd = ["git", "diff", "--name-only", source_commit, "HEAD", "--"] + applies_to
            out = subprocess.check_output(diff_cmd, cwd=repo_path, stderr=subprocess.DEVNULL, text=True).strip()
            changed_files = [f.strip() for f in out.splitlines() if f.strip()]
            if not changed_files:
                return {
                    "status": "valid",
                    "head_commit": head_commit,
                    "source_commit": source_commit,
                    "note": f"HEAD is ahead but target dependencies {applies_to} remain unchanged."
                }
            else:
                return {
                    "status": "review_required",
                    "head_commit": head_commit,
                    "source_commit": source_commit,
                    "changed_dependencies": changed_files
                }
        except Exception:
            pass

    return {
        "status": "review_required",
        "head_commit": head_commit,
        "source_commit": source_commit,
        "reason": f"HEAD ({head_commit}) is ahead of decision commit ({source_commit})"
    }


def init_db() -> sqlite3.Connection:
    """Initialize SQLite FTS5 database."""
    os.makedirs(INDEX_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS records (
                id TEXT PRIMARY KEY,
                filepath TEXT UNIQUE,
                project TEXT,
                type TEXT,
                title TEXT,
                tags TEXT,
                source_commit TEXT,
                status TEXT,
                created_at TEXT,
                updated_at TEXT,
                content TEXT
            );
        """)
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS records_fts USING fts5(
                id UNINDEXED,
                project,
                type,
                title,
                tags,
                content,
                tokenize='unicode61'
            );
        """)
    return conn


def _parse_frontmatter(file_content: str) -> tuple[Dict[str, Any], str]:
    """Extract YAML-like frontmatter between --- fences."""
    frontmatter: Dict[str, Any] = {}
    body = file_content

    if file_content.startswith("---"):
        parts = file_content.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1].strip()
            body = parts[2].strip()
            for line in fm_text.splitlines():
                if ":" in line:
                    key, val = line.split(":", 1)
                    k = key.strip()
                    v = val.strip()
                    if v.startswith("[") and v.endswith("]"):
                        items = [x.strip() for x in v[1:-1].split(",") if x.strip()]
                        frontmatter[k] = items
                    else:
                        frontmatter[k] = v.strip("'\"")
    return frontmatter, body


def sync_vault() -> int:
    """v2: incremental, message-level index (memory_index.py). The v1 full rebuild is kept as _legacy_sync_vault."""
    import memory_index
    return memory_index.sync_index()


def _legacy_sync_vault() -> int:
    """(v1, unused) Scan all markdown files in vault and update FTS5 database."""
    conn = init_db()
    indexed_count = 0

    with conn:
        # Re-index all files
        conn.execute("DELETE FROM records_fts;")
        conn.execute("DELETE FROM records;")

        for root, dirs, files in os.walk(VAULT_ROOT):
            if ".index" in root:
                continue
            for file in files:
                if not file.endswith(".md"):
                    continue
                filepath = os.path.join(root, file)
                rel_path = os.path.relpath(filepath, VAULT_ROOT)

                try:
                    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
                        text = f.read()
                except Exception:
                    continue

                fm, body = _parse_frontmatter(text)

                # Derive record ID
                rec_id = fm.get("id") or os.path.splitext(file)[0].lower()
                rec_type = fm.get("type") or ("index" if file == "INDEX.md" else "note")
                project = fm.get("project")
                if not project:
                    # infer from path
                    rel_parts = rel_path.split(os.sep)
                    if len(rel_parts) > 1 and rel_parts[0] == "projects":
                        project = rel_parts[1]
                    else:
                        project = "global"

                title = fm.get("title")
                if not title:
                    # match first # Header
                    m = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
                    title = m.group(1).strip() if m else file

                tags = fm.get("tags")
                tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags or "")
                source_commit = fm.get("source_commit", "")
                status = fm.get("status", "canonical")
                created_at = fm.get("created_at") or datetime.now().isoformat()
                updated_at = fm.get("updated_at") or created_at

                conn.execute("""
                    INSERT OR REPLACE INTO records (
                        id, filepath, project, type, title, tags, source_commit, status, created_at, updated_at, content
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (rec_id, filepath, project, rec_type, title, tags_str, source_commit, status, created_at, updated_at, body))

                conn.execute("""
                    INSERT INTO records_fts (id, project, type, title, tags, content)
                    VALUES (?, ?, ?, ?, ?, ?);
                """, (rec_id, project, rec_type, title, tags_str, body))

                indexed_count += 1

    conn.close()
    return indexed_count


def memory_search(query: str, project: Optional[str] = None, limit: int = 5, mode: Optional[str] = None) -> List[Dict[str, Any]]:
    """v2: message-level fast FTS5 BM25 search with Turkish folding and AND->OR fallback (memory_index.py)."""
    import memory_index
    return memory_index.search(query, project=project, limit=limit, mode=mode)


def _legacy_memory_search(query: str, project: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
    """(v1, unused) Search memory using SQLite FTS5 BM25 match."""
    conn = init_db()
    # Normalize query for FTS5 (escape special chars)
    clean_query = re.sub(r'[^\w\s-]', '', query).strip()
    if not clean_query:
        conn.close()
        return []

    # Format tokens with prefix match
    fts_tokens = [f'"{tok}"*' for tok in clean_query.split() if tok]
    fts_query = " ".join(fts_tokens)

    sql = """
        SELECT r.id, r.project, r.type, r.title, r.tags, r.source_commit, r.status, r.filepath,
               snippet(records_fts, 5, '==', '==', '...', 15) AS snippet,
               bm25(records_fts) AS rank
        FROM records_fts f
        JOIN records r ON f.id = r.id
        WHERE records_fts MATCH ?
    """
    params = [fts_query]

    if project:
        sql += " AND (r.project = ? OR r.project = 'global')"
        params.append(project)

    sql += " ORDER BY rank LIMIT ?"
    params.append(limit)

    results: List[Dict[str, Any]] = []
    try:
        cur = conn.execute(sql, params)
        for row in cur.fetchall():
            rec_id = row["id"]
            proj = row["project"]
            src_commit = row["source_commit"]

            stale_warning = False
            head_commit = None
            if src_commit and proj and proj != "global":
                head_commit = _get_git_commit(proj)
                if head_commit and head_commit != src_commit:
                    stale_warning = True

            results.append({
                "id": rec_id,
                "project": proj,
                "type": row["type"],
                "title": row["title"],
                "tags": row["tags"],
                "status": row["status"],
                "snippet": row["snippet"],
                "source_commit": src_commit,
                "head_commit": head_commit,
                "stale_warning": stale_warning,
                "path": row["filepath"]
            })
    except Exception as e:
        # Fallback to simple LIKE search if FTS syntax error
        cur = conn.execute("""
            SELECT id, project, type, title, tags, source_commit, status, filepath,
                   substr(content, 1, 120) AS snippet
            FROM records
            WHERE (title LIKE ? OR content LIKE ?)
            LIMIT ?
        """, (f"%{clean_query}%", f"%{clean_query}%", limit))
        for row in cur.fetchall():
            results.append({
                "id": row["id"],
                "project": row["project"],
                "type": row["type"],
                "title": row["title"],
                "tags": row["tags"],
                "status": row["status"],
                "snippet": row["snippet"] + "...",
                "source_commit": row["source_commit"],
                "stale_warning": False,
                "path": row["filepath"]
            })

    conn.close()
    return results


def memory_get(record_id: str) -> Optional[Dict[str, Any]]:
    """v2: resolve a frontmatter id, 'path#line' / 'path#a:b' chunk id or a path (memory_index.py)."""
    import memory_index
    return memory_index.get(record_id)


def _legacy_memory_get(record_id: str) -> Optional[Dict[str, Any]]:
    """(v1, unused) Retrieve full record content and metadata by ID."""
    conn = init_db()
    cur = conn.execute("SELECT * FROM records WHERE id = ? OR filepath LIKE ?", (record_id, f"%{record_id}%"))
    row = cur.fetchone()
    conn.close()

    if not row:
        return None

    proj = row["project"]
    src_commit = row["source_commit"]
    stale_warning = False
    head_commit = None

    if src_commit and proj and proj != "global":
        head_commit = _get_git_commit(proj)
        if head_commit and head_commit != src_commit:
            stale_warning = True

    return {
        "id": row["id"],
        "project": proj,
        "type": row["type"],
        "title": row["title"],
        "tags": row["tags"],
        "status": row["status"],
        "source_commit": src_commit,
        "head_commit": head_commit,
        "stale_warning": stale_warning,
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "content": row["content"],
        "filepath": row["filepath"]
    }


def _safe_project_dir(project: str, subfolder: str = "") -> str:
    """Ensure project and subfolder are strictly within VAULT_ROOT (prevents path traversal)."""
    clean_project = re.sub(r'[^a-zA-Z0-9_\-]', '', project.strip()) or "global"
    clean_subfolder = re.sub(r'[^a-zA-Z0-9_\-]', '', subfolder.strip())
    
    if clean_subfolder:
        target = os.path.join(VAULT_ROOT, "projects", clean_project, clean_subfolder)
    else:
        target = os.path.join(VAULT_ROOT, "projects", clean_project)

    os.makedirs(target, exist_ok=True)
    real_vault = os.path.realpath(VAULT_ROOT)
    real_target = os.path.realpath(target)
    if not real_target.startswith(real_vault):
        raise ValueError(f"Security error: Target path '{target}' is outside vault '{VAULT_ROOT}'")
    return target


def memory_propose(project: str, rtype: str, title: str, content: str, tags: List[str] = []) -> Dict[str, Any]:
    """Create a new proposal in the memory vault with atomic write and collision protection."""
    date_tag = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:35] or "item"
    rec_id = f"{rtype}-{slug}-{date_tag}"

    subfolder = "decisions" if rtype == "decision" else ("lessons" if rtype == "lesson" else "")
    target_dir = _safe_project_dir(project, subfolder)
    target_file = os.path.join(target_dir, f"{rec_id.upper()}.md")

    head_commit = _get_git_commit(project) or ""
    now_str = datetime.now().isoformat()
    tags_yaml = "[" + ", ".join(tags) + "]" if tags else "[]"

    markdown = f"""---
id: {rec_id}
type: {rtype}
project: {project}
title: {title}
status: proposal
source_commit: {head_commit}
tags: {tags_yaml}
created_at: {now_str}
---

# {title}

{content}
"""

    # Atomic create: fail if already exists to prevent accidental overwrite
    try:
        with open(target_file, "x", encoding="utf-8") as f:
            f.write(markdown)
    except FileExistsError:
        # Fallback with microseconds if collision occurs
        rec_id = f"{rec_id}-{datetime.now().microsecond}"
        target_file = os.path.join(target_dir, f"{rec_id.upper()}.md")
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(markdown)

    sync_vault()
    return {
        "success": True,
        "id": rec_id,
        "filepath": target_file,
        "status": "proposal",
        "source_commit": head_commit
    }


def memory_commit(record_id: str) -> Dict[str, Any]:
    """Promote a proposal to canonical approved status with strict state verification."""
    rec = memory_get(record_id)
    if not rec:
        return {"success": False, "error": f"Record not found: {record_id}"}

    current_status = (rec.get("status") or "").lower()
    if current_status == "canonical":
        return {"success": True, "id": record_id, "status": "canonical", "notice": "Already canonical"}
    if current_status != "proposal":
        return {"success": False, "error": f"Record '{record_id}' is not in 'proposal' state (current: '{current_status}')"}

    filepath = rec.get("filepath")
    if not filepath or not os.path.isfile(filepath):
        return {"success": False, "error": f"File path for record '{record_id}' does not exist"}

    with open(filepath, "r", encoding="utf-8") as f:
        text = f.read()

    new_text, count = re.subn(r"^status:\s*proposal", "status: canonical", text, count=1, flags=re.MULTILINE)
    if count == 0:
        return {"success": False, "error": "Frontmatter 'status: proposal' could not be found to promote"}

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(new_text)

    sync_vault()
    return {"success": True, "id": record_id, "status": "canonical"}


def memory_handoff(project: str, summary: str, decisions: List[str] = [], unresolved: List[str] = []) -> Dict[str, Any]:
    """Create a structured handoff note for agent transitions with collision-safe timestamp."""
    target_dir = _safe_project_dir(project, "handoffs")

    date_slug = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    rec_id = f"handoff-{date_slug}"
    target_file = os.path.join(target_dir, f"HANDOFF-{date_slug}.md")

    head_commit = _get_git_commit(project) or ""
    now_str = datetime.now().isoformat()

    decisions_md = "\n".join([f"- {d}" for d in decisions]) if decisions else "- Yok"
    unresolved_md = "\n".join([f"- [ ] {u}" for u in unresolved]) if unresolved else "- Tüm görevler tamamlandı."

    markdown = f"""---
id: {rec_id}
type: handoff
project: {project}
title: Oturum Devri (Handoff) - {date_slug}
status: canonical
source_commit: {head_commit}
created_at: {now_str}
---

# 🔄 Oturum Devri (Session Handoff): {project}

## 📋 Özet
{summary}

## 🏛️ Alınan Temel Kararlar
{decisions_md}

## ⏳ Açık ve Kalan İşler
{unresolved_md}
"""

    with open(target_file, "w", encoding="utf-8") as f:
        f.write(markdown)

    sync_vault()
    return {
        "success": True,
        "id": rec_id,
        "filepath": target_file,
        "source_commit": head_commit
    }


if __name__ == "__main__":
    count = sync_vault()
    print(f"Synced {count} records in AI-Memory vault.")
    res = memory_search("silent exempts")
    print(json.dumps(res, indent=2))
