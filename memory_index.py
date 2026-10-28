"""
Universal Memory v2 index: incremental, message-level, Turkish-folded FTS5 over the Obsidian vault.

Why it exists (found 2026-10-16 in v1):
  * v1 keyed every note by its FILE NAME (``2026-10-16``, ``readme``): 865 indexed notes collapsed into 53 records, so a hit's
    title/path could belong to a different note and ``memory_get`` reached only the last note with that name.
  * v1 re-indexed once at server start only: everything the archive daemon wrote afterwards was invisible.
  * v1 indexed a whole 2,400-line session as ONE document: hits had no message, time or line to jump to.
  * v1 required every query word (AND) and did not fold Turkish letters/inflections.

v2: one FTS row per MESSAGE (``## ...`` header / ChatGPT Q-A marker), unique ids (``relative/path.md#line``), per-file
change detection (mtime+size) so a refresh is cheap, Turkish letter folding and light stemming, AND -> OR fallback,
project = top-level vault folder, results carry speaker, time, agent, session and the matching line.
"""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from itertools import islice
from typing import Any, Dict, List, Optional, Tuple

MAX_CHUNK_CHARS = 4500
FRESH_CHECK_SECONDS = 15
GET_MAX_CHARS = 30000

_TR = str.maketrans({
    "ı": "i", "İ": "i", "ş": "s", "Ş": "s", "ğ": "g", "Ğ": "g",
    "ç": "c", "Ç": "c", "ö": "o", "Ö": "o", "ü": "u", "Ü": "u",
})
_STOP = {"ve", "bir", "bu", "su", "icin", "ile", "de", "da", "mi", "mu", "ne", "the", "and", "of", "to", "in", "a"}
_HDR = re.compile(r"^(?:##\s+|-{8,}\s*[QA]\s*-{8,}\s*$)")
_TIME = re.compile(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]\s*$")
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
_SESSION = re.compile(r"\[([0-9a-f]{6,8})\]\s*$")

_lock = threading.Lock()
_last_check = 0.0


def fold(s: str) -> str:
    """Lower-case and map Turkish letters to ASCII, 1:1 (length preserved so positions line up with the original)."""
    return s.translate(_TR).lower()


def _vault_root() -> str:
    import memory_engine  # lazy: memory_engine imports this module lazily too
    return memory_engine.VAULT_ROOT


def _db_path() -> str:
    return os.path.join(_vault_root(), ".index", "memory_v2.sqlite")


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(_db_path()), exist_ok=True)
    conn = sqlite3.connect(_db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS files(
            path TEXT PRIMARY KEY, mtime REAL, size INTEGER, project TEXT, pnorm TEXT, agent TEXT, session TEXT,
            title TEXT, date TEXT, rtype TEXT, rid TEXT, status TEXT, source_commit TEXT, tags TEXT,
            created_at TEXT, updated_at TEXT);
        CREATE INDEX IF NOT EXISTS files_rid ON files(rid);
        CREATE TABLE IF NOT EXISTS chunk_map(path TEXT, rowid_ INTEGER, hash TEXT);
        CREATE INDEX IF NOT EXISTS chunk_map_path ON chunk_map(path);
        CREATE INDEX IF NOT EXISTS chunk_map_hash ON chunk_map(hash);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
            body, heading, title, project, tags,
            path UNINDEXED, line UNINDEXED, endline UNINDEXED, date UNINDEXED, ts UNINDEXED, speaker UNINDEXED,
            pnorm UNINDEXED,
            tokenize='unicode61 remove_diacritics 2');
        
        -- Universal Memory v3: Wikilinks & Graph Layer
        CREATE TABLE IF NOT EXISTS memory_nodes (
            id TEXT PRIMARY KEY,
            path TEXT NOT NULL UNIQUE,
            project TEXT NOT NULL,
            type TEXT NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS memory_edges (
            source_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            relation TEXT NOT NULL,
            PRIMARY KEY (source_id, target_id, relation)
        );
        CREATE INDEX IF NOT EXISTS idx_edges_target ON memory_edges(target_id, relation);
        CREATE INDEX IF NOT EXISTS idx_edges_source ON memory_edges(source_id, relation);
    """)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(files)")]
    if "tzlocal" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN tzlocal INTEGER DEFAULT 0")
    for extra in ("valid_from", "valid_until", "source_event_time", "ingestion_time", "superseded_by", "agent_id", "run_id"):
        if extra not in cols:
            conn.execute(f"ALTER TABLE files ADD COLUMN {extra} TEXT DEFAULT ''")
    conn.commit()
    return conn


# --------------------------------------------------------------------------- parsing

def _norm_project(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", fold(name or ""))


def _split_frontmatter(lines: List[str]) -> Tuple[Dict[str, str], int]:
    """(frontmatter dict, number of lines it occupies). Only simple ``key: value`` lines are read."""
    if not lines or lines[0].strip() != "---":
        return {}, 0
    fm: Dict[str, str] = {}
    for i in range(1, min(len(lines), 60)):
        if lines[i].strip() == "---":
            return fm, i + 1
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", lines[i])
        if m:
            fm[m.group(1)] = m.group(2).strip().strip("'\"")
    return {}, 0


def _file_meta(rel: str, lines: List[str], fm: Dict[str, str], st: os.stat_result) -> Dict[str, Any]:
    parts = rel.split(os.sep)
    folder = parts[-2] if len(parts) > 1 else ""
    top = parts[0] if len(parts) > 1 else ""
    if parts[0] == "projects" and len(parts) > 2:
        project = fm.get("project") or parts[1]
    else:
        project = fm.get("project") or top or "global"

    session = ""
    m = _SESSION.search(folder)
    if m:
        session = m.group(1)

    agent = ""
    for line in lines[:25]:
        am = re.search(r"\*\*Ajan:\*\*\s*`?([^`]+?)`?\s*$", line)
        if am:
            agent = re.sub(r"[^\w\s().+-]", "", am.group(1)).strip()
            break
    if not agent:
        if "[Claude_Code]" in folder:
            agent = "Claude Code"
        elif "[ChatGPT]" in folder:
            agent = "ChatGPT"

    # Notes the archive daemon writes carry "- **Saat Dilimi:** Yerel (UTC+03:00)" since 2026-10-16; older notes are UTC.
    tzlocal = 1 if any(("Saat Dilimi" in l and "Yerel" in l) for l in lines[:25]) else 0

    dm = _DATE.search(os.path.basename(rel)) or _DATE.search(folder)
    date = dm.group(1) if dm else (fm.get("created_at", "")[:10] or datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"))

    title = fm.get("title")
    if not title:
        t = re.sub(r"^\[[^\]]*\]_?", "", folder)            # leading [date] / [Claude_Code]
        t = re.sub(r"_?\[[0-9a-f]{6,8}\]\s*$", "", t)       # trailing [session id]
        t = t.replace("_", " ").strip()
        title = t or os.path.splitext(parts[-1])[0]
    name = os.path.basename(rel).lower()
    rtype = fm.get("type") or ("index" if name == "index.md" else "readme" if name == "readme.md" and len(parts) > 1 else "note")
    iso = datetime.fromtimestamp(st.st_mtime).isoformat()
    return {
        "project": project, "pnorm": _norm_project(project), "agent": agent, "session": session, "title": title,
        "date": date, "tzlocal": tzlocal, "rtype": rtype, "rid": fm.get("id", ""), "status": fm.get("status", "canonical"),
        "source_commit": fm.get("source_commit", ""), "tags": fm.get("tags", ""),
        "created_at": fm.get("created_at") or iso, "updated_at": fm.get("updated_at") or fm.get("created_at") or iso,
        "valid_from": fm.get("valid_from", ""), "valid_until": fm.get("valid_until", ""),
        "source_event_time": fm.get("source_event_time", ""), "ingestion_time": fm.get("ingestion_time", ""),
        "superseded_by": fm.get("superseded_by", ""), "agent_id": fm.get("agent_id", ""), "run_id": fm.get("run_id", ""),
    }


def _chunks(lines: List[str], first: int) -> List[Tuple[int, int, str]]:
    """Split into (start_line, end_line, heading), 1-based inclusive. Boundaries: ``## `` headers and ChatGPT Q/A markers."""
    n = len(lines)
    starts: List[Tuple[int, str]] = []
    cur_heading = ""
    for i in range(first, n):
        if _HDR.match(lines[i]):
            starts.append((i, lines[i].strip().lstrip("#").strip("- ").strip()))
    boundaries: List[Tuple[int, str]] = []
    if not starts or starts[0][0] > first:
        boundaries.append((first, ""))
    boundaries.extend(starts)
    out: List[Tuple[int, int, str]] = []
    for idx, (s, heading) in enumerate(boundaries):
        e = (boundaries[idx + 1][0] if idx + 1 < len(boundaries) else n) - 1
        if e < s:
            continue
        # cap size: split a long message at blank lines so a hit points near the real spot
        pos = s
        size = 0
        for j in range(s, e + 1):
            size += len(lines[j]) + 1
            if size >= MAX_CHUNK_CHARS and (not lines[j].strip() or size >= MAX_CHUNK_CHARS * 2):
                out.append((pos + 1, j + 1, heading))
                pos, size = j + 1, 0
        if pos <= e:
            out.append((pos + 1, e + 1, heading))
        cur_heading = heading
    return [c for c in out if c[1] >= c[0]]


def _speaker_ts(heading: str) -> Tuple[str, str]:
    ts = ""
    m = _TIME.search(heading)
    if m:
        ts = m.group(1)
        heading = heading[: m.start()].strip()
    speaker = re.sub(r"[^\w\s()./+-]", "", heading, flags=re.UNICODE).strip()
    if speaker in ("Q", "A"):
        speaker = "KULLANICI (Q)" if speaker == "Q" else "ASİSTAN (A)"
    return speaker, ts


_WIKILINK_RE = re.compile(r"\[\[([^\]\|#]+)(?:#[^\]\|]+)?(?:\|[^\]]+)?\]\]")
_TYPED_EDGE_RE = re.compile(r"^\s*-\s*(supersedes|contradicts|depends_on|evidenced_by|related_to|applies_to):\s*\[\[([^\]\|#]+)", re.IGNORECASE)


def _extract_edges(source_id: str, lines: List[str]) -> List[Tuple[str, str, str]]:
    """Extract Wikilinks [[target]] and typed relations (supersedes, depends_on, etc.)."""
    edges: List[Tuple[str, str, str]] = []
    seen = set()
    for line in lines:
        typed_m = _TYPED_EDGE_RE.search(line)
        if typed_m:
            rel_type = typed_m.group(1).lower()
            target_raw = typed_m.group(2).strip()
            edge_key = (source_id, target_raw, rel_type)
            if edge_key not in seen:
                edges.append(edge_key)
                seen.add(edge_key)
        else:
            for m in _WIKILINK_RE.finditer(line):
                target_raw = m.group(1).strip()
                edge_key = (source_id, target_raw, "related_to")
                if edge_key not in seen:
                    edges.append(edge_key)
                    seen.add(edge_key)
    return edges


# --------------------------------------------------------------------------- indexing

def _index_file(conn: sqlite3.Connection, abs_path: str, rel: str, st: os.stat_result) -> int:
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().split("\n")
    except OSError:
        return 0
    fm, fm_lines = _split_frontmatter(lines)
    meta = _file_meta(rel, lines, fm, st)

    old = conn.execute("SELECT rowid_ FROM chunk_map WHERE path = ?", (rel,)).fetchall()
    for r in old:
        conn.execute("DELETE FROM chunks WHERE rowid = ?", (r[0],))
    conn.execute("DELETE FROM chunk_map WHERE path = ?", (rel,))

    conn.execute(
        """INSERT OR REPLACE INTO files(path, mtime, size, project, pnorm, agent, session, title, date, rtype, rid,
           status, source_commit, tags, created_at, updated_at, tzlocal, valid_from, valid_until, source_event_time,
           ingestion_time, superseded_by, agent_id, run_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rel, st.st_mtime, st.st_size, meta["project"], meta["pnorm"], meta["agent"], meta["session"], meta["title"],
         meta["date"], meta["rtype"], meta["rid"], meta["status"], meta["source_commit"], meta["tags"],
         meta["created_at"], meta["updated_at"], meta["tzlocal"], meta["valid_from"], meta["valid_until"],
         meta["source_event_time"], meta["ingestion_time"], meta["superseded_by"], meta["agent_id"], meta["run_id"]),
    )

    # Wikilinks & Graph node/edge indexing
    node_id = meta["rid"] or rel.replace(os.sep, "/").removesuffix(".md")
    conn.execute(
        "INSERT OR REPLACE INTO memory_nodes(id, path, project, type, status) VALUES (?,?,?,?,?)",
        (node_id, rel, meta["project"], meta["rtype"], meta["status"])
    )
    conn.execute("DELETE FROM memory_edges WHERE source_id = ?", (node_id,))
    for s_id, t_id, r_type in _extract_edges(node_id, lines):
        conn.execute(
            "INSERT OR IGNORE INTO memory_edges(source_id, target_id, relation) VALUES (?,?,?)",
            (s_id, t_id, r_type)
        )

    count = 0
    for start, end, heading in _chunks(lines, fm_lines):
        text = "\n".join(lines[start - 1:end])
        if not text.strip():
            continue
        speaker, ts = _speaker_ts(heading)
        cur = conn.execute(
            """INSERT INTO chunks(body, heading, title, project, tags, path, line, endline, date, ts, speaker, pnorm)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fold(text), fold(heading), fold(meta["title"]), fold(meta["project"]), fold(meta["tags"]),
             rel, start, end, meta["date"], ts, speaker, meta["pnorm"]),
        )
        conn.execute("INSERT INTO chunk_map(path, rowid_, hash) VALUES (?,?,?)",
                     (rel, cur.lastrowid, hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()))
        count += 1
    return count


def sync_index(force: bool = False) -> int:
    """Index new/changed notes, drop deleted ones. Returns the number of files (re)indexed."""
    root = _vault_root()
    with _lock:
        conn = connect()
        conn.isolation_level = None  # explicit BEGIN/COMMIT below
        try:
            known = {r["path"]: (r["mtime"], r["size"]) for r in conn.execute("SELECT path, mtime, size FROM files")}
            seen = set()
            changed = 0
            conn.execute("BEGIN IMMEDIATE")
            for cur_root, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d != ".index" and not d.startswith(".")]
                for name in files:
                    if not name.endswith(".md"):
                        continue
                    abs_path = os.path.join(cur_root, name)
                    rel = os.path.relpath(abs_path, root)
                    try:
                        st = os.stat(abs_path)
                    except OSError:
                        continue
                    seen.add(rel)
                    if not force and known.get(rel) == (st.st_mtime, st.st_size):
                        continue
                    _index_file(conn, abs_path, rel, st)
                    changed += 1
            for gone in set(known) - seen:
                for r in conn.execute("SELECT rowid_ FROM chunk_map WHERE path = ?", (gone,)).fetchall():
                    conn.execute("DELETE FROM chunks WHERE rowid = ?", (r[0],))
                conn.execute("DELETE FROM chunk_map WHERE path = ?", (gone,))
                conn.execute("DELETE FROM files WHERE path = ?", (gone,))
            conn.execute("COMMIT")
            return changed
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except sqlite3.Error:
                pass
            raise
        finally:
            conn.close()


def ensure_fresh() -> None:
    """Cheap, throttled refresh so notes the archive daemon wrote a minute ago are searchable."""
    global _last_check
    now = time.time()
    if now - _last_check < FRESH_CHECK_SECONDS:
        return
    _last_check = now
    try:
        sync_index()
    except sqlite3.OperationalError:
        pass  # another process is indexing right now; the existing index is still readable


def local_when(date: str, ts: str, tzlocal: int) -> str:
    """'YYYY-MM-DD HH:MM[:SS]' in LOCAL time. Notes written before 2026-10-16 are UTC and are converted; notes that say
    'Saat Dilimi: Yerel' (or have no clock time) are shown as stored."""
    if not ts or tzlocal:
        return f"{date} {ts}".strip()
    try:
        fmt = "%Y-%m-%d %H:%M:%S" if ts.count(":") == 2 else "%Y-%m-%d %H:%M"
        utc = datetime.strptime(f"{date} {ts}", fmt).replace(tzinfo=timezone.utc)
        return utc.astimezone().strftime(fmt)
    except ValueError:
        return f"{date} {ts}".strip()


# --------------------------------------------------------------------------- search

def _stem(tok: str) -> str:
    n = len(tok)
    if n >= 9:
        return tok[:-3]
    if n >= 7:
        return tok[:-2]
    return tok


def _query_parts(query: str) -> Tuple[List[str], List[str]]:
    q = fold(query)
    phrases = [p.strip() for p in re.findall(r'"([^"]+)"', q) if p.strip()]
    rest = re.sub(r'"[^"]*"', " ", q)
    toks = [t for t in re.findall(r"\w+", rest, flags=re.UNICODE) if len(t) >= 2 and t not in _STOP]
    return phrases, toks


def _read_lines(rel: str, start: int, end: int) -> str:
    try:
        with open(os.path.join(_vault_root(), rel), "r", encoding="utf-8", errors="replace") as f:
            return "\n".join(l.rstrip("\n") for l in islice(f, start - 1, end))
    except OSError:
        return ""


def _snippet(text: str, stems: List[str], width: int = 300) -> Tuple[str, int]:
    """(snippet with ==highlight==, offset line inside the chunk of the first match)."""
    f = fold(text)
    pos = [f.find(s) for s in stems if s and f.find(s) >= 0]
    first = min(pos) if pos else 0
    start = max(0, first - 100)
    piece, fpiece = text[start:start + width], f[start:start + width]
    spans: List[Tuple[int, int]] = []
    for s in stems:
        if not s:
            continue
        for m in re.finditer(re.escape(s) + r"\w*", fpiece):
            spans.append((m.start(), m.end()))
    spans.sort()
    out, last = [], 0
    for a, b in spans:
        if a < last:
            continue
        out.append(piece[last:a] + "==" + piece[a:b] + "==")
        last = b
    out.append(piece[last:])
    snip = ("..." if start else "") + "".join(out).strip() + ("..." if start + width < len(text) else "")
    return snip.replace("\n", " "), text[:first].count("\n")


def _run(conn: sqlite3.Connection, fts: str, pnorm: Optional[str], cands: int, order_by: Optional[str] = None) -> List[sqlite3.Row]:
    sql = ("SELECT rowid, path, line, endline, date, ts, speaker, "
           "bm25(chunks, 1.0, 3.0, 2.0, 0.5, 0.5) AS rank FROM chunks WHERE chunks MATCH ?")
    params: List[Any] = [fts]
    if pnorm:
        sql += " AND pnorm LIKE ?"
        params.append(f"%{pnorm}%")
    ob = (order_by or "").lower().strip()
    if ob == "time_asc":
        sql += " ORDER BY date ASC, ts ASC, line ASC LIMIT ?"
    elif ob == "time_desc":
        sql += " ORDER BY date DESC, ts DESC, line DESC LIMIT ?"
    else:
        sql += " ORDER BY rank LIMIT ?"
    params.append(cands)
    try:
        return conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        return []


def search(query: str, project: Optional[str] = None, limit: int = 5, mode: Optional[str] = None,
           as_of: Optional[str] = None, include_invalid: bool = False,
           order_by: Optional[str] = None, surround: int = 0,
           context_lines: Optional[int] = None) -> List[Dict[str, Any]]:
    """Fast, message-level FTS5 BM25 search with Turkish folding and AND -> OR fallback.
    Bi-temporal: by default only records valid now (or at ``as_of``) are returned; ``include_invalid`` returns history.
    order_by: 'relevance' (default BM25), 'time_asc', or 'time_desc'.
    surround / context_lines: optional integer lines of surrounding context included in 'context'."""
    import memory_engine
    from bitemporal import record_is_valid
    ensure_fresh()
    phrases, toks = _query_parts(query)
    if not phrases and not toks:
        return []
    if not (query or "").strip():
        return []
    stems = [_stem(t) for t in toks] + phrases
    pnorm = _norm_project(project) if project and project.lower() != "global" else None
    and_q = " ".join([f'"{p}"' for p in phrases] + [f'"{_stem(t)}"*' for t in toks])
    or_q = " OR ".join([f'"{p}"' for p in phrases] + [f'"{_stem(t)}"*' for t in toks])

    ob = (order_by or "").lower().strip()
    is_time_sort = ob in ("time_asc", "time_desc")
    ctx = context_lines if context_lines is not None else surround
    ctx = max(0, int(ctx or 0))

    conn = connect()
    try:
        cands = max(limit * 20, 100) if is_time_sort else max(limit * 8, 40)
        files: Dict[str, Optional[sqlite3.Row]] = {}

        def file_of(rel: str) -> Optional[sqlite3.Row]:
            if rel not in files:
                files[rel] = conn.execute("SELECT * FROM files WHERE path = ?", (rel,)).fetchone()
            return files[rel]

        # keyword side: execute query with requested sort
        kw: List[Dict[str, Any]] = []
        and_rows = _run(conn, and_q, pnorm, cands, order_by=ob)
        seen_ids = {(r["path"], r["line"]) for r in and_rows}
        or_rows: List[sqlite3.Row] = []
        if len(and_rows) < limit * 2 and len(toks) + len(phrases) > 1:
            for r in _run(conn, or_q, pnorm, cands, order_by=ob):
                if (r["path"], r["line"]) not in seen_ids:
                    or_rows.append(r)

        if is_time_sort:
            all_rows = list(and_rows) + list(or_rows)
            def time_key(r: sqlite3.Row) -> tuple[str, str, int]:
                return (r["date"] or "", r["ts"] or "", r["line"] or 0)
            all_rows.sort(key=time_key, reverse=(ob == "time_desc"))
            kw = [dict(r) for r in all_rows]
        else:
            for block in (and_rows, or_rows):
                part: List[Tuple[float, Dict[str, Any]]] = []
                for r in block:
                    f = file_of(r["path"])
                    if f is None:
                        continue
                    penalty = 1.5 if f["rtype"] == "readme" else 0.0
                    part.append((r["rank"] + penalty, dict(r)))
                part.sort(key=lambda x: x[0])
                kw.extend(d for _, d in part)

        results: List[Dict[str, Any]] = []
        per_file: Dict[str, int] = {}
        for r in kw:
            f = file_of(r["path"])
            if f is None or per_file.get(r["path"], 0) >= 2:
                continue
            if not include_invalid and not record_is_valid(f, as_of):
                continue
            per_file[r["path"]] = per_file.get(r["path"], 0) + 1
            text = _read_lines(r["path"], r["line"], r["endline"])
            snip, off = _snippet(text, stems)
            head = None
            stale = False
            sc = f["source_commit"]
            if sc and f["project"] and f["project"] != "global":
                head = memory_engine._get_git_commit(f["project"])
                stale = bool(head and head != sc)

            res_item = {
                "id": f"{r['path'].replace(os.sep, '/')}#{r['line']}",
                "project": f["project"],
                "type": f["rtype"],
                "title": f["title"],
                "agent": f["agent"] or ("Antigravity" if "ANTIGRAVITY" in (r["speaker"] or "").upper() else ""),
                "session": f["session"],
                "speaker": r["speaker"],
                "when": local_when(r["date"], r["ts"], f["tzlocal"]),
                "via": "kelime",
                "cos": None,
                "snippet": snip,
                "match_line": r["line"] + off,
                "path": os.path.join(_vault_root(), r["path"]),
                "status": f["status"],
                "valid_from": f["valid_from"],
                "valid_until": f["valid_until"],
                "superseded_by": f["superseded_by"],
                "source_commit": sc,
                "head_commit": head,
                "stale_warning": stale,
            }
            if ctx > 0:
                s_start = max(1, r["line"] - ctx)
                s_end = r["endline"] + ctx
                res_item["context"] = _read_lines(r["path"], s_start, s_end)
                res_item["context_range"] = f"{s_start}-{s_end}"

            results.append(res_item)
            if len(results) >= limit:
                break
        return results
    finally:
        conn.close()


# --------------------------------------------------------------------------- get

def _file_row(conn: sqlite3.Connection, ref: str) -> Optional[sqlite3.Row]:
    ref_norm = ref.replace("/", os.sep).replace("\\", os.sep)
    root = _vault_root()
    if os.path.isabs(ref_norm):
        try:
            ref_norm = os.path.relpath(ref_norm, root)
        except ValueError:
            pass
    row = conn.execute("SELECT * FROM files WHERE path = ?", (ref_norm,)).fetchone()
    if row:
        return row
    if not ref_norm.lower().endswith(".md"):
        row = conn.execute("SELECT * FROM files WHERE path = ?", (ref_norm + ".md",)).fetchone()
        if row:
            return row
    row = conn.execute("SELECT * FROM files WHERE replace(path, '\\', '/') = ? OR replace(path, '/', '\\') = ?",
                       (ref.replace("\\", "/"), ref.replace("/", "\\"))).fetchone()
    if row:
        return row
    base = os.path.basename(ref_norm)
    if base:
        row = conn.execute("SELECT * FROM files WHERE path LIKE ? OR lower(path) LIKE ? ORDER BY date DESC, mtime DESC LIMIT 1",
                           (f"%{os.sep}{base}", f"%{os.sep}{base.lower()}")).fetchone()
        if row:
            return row
    return None


def _record(conn: sqlite3.Connection, f: sqlite3.Row, start: int, end: int, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    import memory_engine
    text = _read_lines(f["path"], start, end)
    truncated = False
    if len(text) > GET_MAX_CHARS:
        text = text[:GET_MAX_CHARS] + "\n...[kesildi: devamı için 'dosya#satır' veya 'dosya#baş:son' kullan]"
        truncated = True

    # Parse applies_to dependencies for Git provenance
    applies_to: List[str] = []
    for line in text.splitlines()[:50]:
        line_s = line.strip()
        if line_s.startswith("- applies_to:") or line_s.startswith("applies_to:"):
            val = line_s.split(":", 1)[1].strip()
            if val.startswith("[") and val.endswith("]"):
                applies_to.extend([x.strip("'\" ") for x in val[1:-1].split(",") if x.strip()])
            else:
                applies_to.append(val.strip("'\" "))

    validity = memory_engine.check_validity(f["project"], f["source_commit"], applies_to)
    head = validity.get("head_commit")
    stale = validity.get("status") == "review_required"

    # Wikilinks & Graph relations
    node_id = f["rid"] or f["path"].replace(os.sep, "/").removesuffix(".md")
    base_name = os.path.basename(f["path"]).removesuffix(".md")
    outgoing = []
    for r in conn.execute(
        "SELECT target_id, relation FROM memory_edges WHERE source_id = ? OR source_id = ?",
        (node_id, f["path"])
    ).fetchall():
        outgoing.append({"target": r["target_id"], "relation": r["relation"]})

    backlinks = []
    for r in conn.execute(
        """SELECT e.source_id, e.relation, n.path, n.project, n.type 
           FROM memory_edges e 
           LEFT JOIN memory_nodes n ON n.id = e.source_id 
           WHERE e.target_id = ? OR e.target_id = ? OR e.target_id = ?""",
        (node_id, f["path"], base_name)
    ).fetchall():
        backlinks.append({
            "source": r["source_id"],
            "relation": r["relation"],
            "path": r["path"],
            "project": r["project"],
            "type": r["type"]
        })

    out = {
        "id": f["rid"] or f"{f['path'].replace(os.sep, '/')}#{start}",
        "project": f["project"], "type": f["rtype"], "title": f["title"], "tags": f["tags"], "status": f["status"],
        "agent": f["agent"], "session": f["session"], "date": f["date"],
        "source_commit": f["source_commit"], "head_commit": head, "stale_warning": stale,
        "validity": validity,
        "valid_from": f["valid_from"], "valid_until": f["valid_until"], "source_event_time": f["source_event_time"],
        "ingestion_time": f["ingestion_time"], "superseded_by": f["superseded_by"],
        "agent_id": f["agent_id"], "run_id": f["run_id"],
        "relations": {
            "outgoing": outgoing,
            "backlinks": backlinks
        },
        "created_at": f["created_at"], "updated_at": f["updated_at"],
        "lines": f"{start}-{end}", "truncated": truncated,
        "content": text, "filepath": os.path.join(_vault_root(), f["path"]),
    }
    if extra:
        out.update(extra)
    return out


def get(record_id: str, surround: int = 0) -> Optional[Dict[str, Any]]:
    """Resolve a frontmatter id, ``path#line`` / ``path#a:b`` chunk id, a path, or a legacy bare name (returns matches).
    Accepts ``surround`` to expand the line range for chunk lookups."""
    ensure_fresh()
    rid = (record_id or "").strip()
    if not rid:
        return None
    conn = connect()
    try:
        f = conn.execute("SELECT * FROM files WHERE rid = ?", (rid,)).fetchone()
        if f:
            return _record(conn, f, 1, 10 ** 6)

        m = re.match(r"^(.*?)#(?:L)?(\d+)(?:[-:](?:L)?(\d+))?$", rid, re.IGNORECASE)
        if m:
            base_ref = m.group(1).strip()
            line = int(m.group(2))
            end_line = int(m.group(3)) if m.group(3) else None

            f = _file_row(conn, base_ref)
            if f is None and base_ref:
                f = conn.execute("SELECT * FROM files WHERE rid = ?", (base_ref,)).fetchone()
            if f is None and base_ref:
                f = conn.execute(
                    "SELECT * FROM files WHERE path LIKE ? OR replace(path, '\\', '/') LIKE ? ORDER BY date DESC LIMIT 1",
                    (f"%{base_ref.replace('/', os.sep)}%", f"%{base_ref.replace(os.sep, '/')}%")
                ).fetchone()
            if f is None:
                return None

            if end_line is not None:
                s = max(1, line - surround) if surround else line
                e = end_line + surround if surround else end_line
                return _record(conn, f, s, e)

            c = conn.execute(
                "SELECT line, endline FROM chunks WHERE path = ? AND line <= ? AND endline >= ? LIMIT 1",
                (f["path"], line, line)
            ).fetchone()
            start = c["line"] if c else max(1, line - 5)
            end = c["endline"] if c else line + 60
            if surround:
                start = max(1, start - surround)
                end = end + surround
            return _record(conn, f, start, end)

        f = _file_row(conn, rid)
        if f:
            return _record(conn, f, 1, 10 ** 6)

        # legacy v1 ids were bare file names ('2026-10-16', 'readme'): several notes share them, so list them
        name = rid.lower() if rid.lower().endswith(".md") else rid.lower() + ".md"
        rows = conn.execute("SELECT * FROM files WHERE lower(path) = ? OR lower(path) LIKE ? ORDER BY date DESC, mtime DESC LIMIT 60",
                            (name, f"%{os.sep}{name}")).fetchall()
        rows = [r for r in rows if os.path.basename(r["path"]).lower() == name][:12]
        if not rows:
            return None
        newest = rows[0]
        extra = {
            "ambiguous": len(rows) > 1,
            "matches": [{"id": r["path"].replace(os.sep, "/"), "title": r["title"], "date": r["date"], "agent": r["agent"]} for r in rows],
        }
        return _record(conn, newest, 1, 10 ** 6, extra)
    finally:
        conn.close()
