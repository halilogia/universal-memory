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
import json
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

        -- Universal Memory Salience & Recall Counter
        CREATE TABLE IF NOT EXISTS recall_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entry_id TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            weight REAL NOT NULL DEFAULT 1.0
        );
        CREATE INDEX IF NOT EXISTS idx_recall_events_entry ON recall_events(entry_id);
        CREATE INDEX IF NOT EXISTS idx_recall_events_ts ON recall_events(timestamp);

        CREATE TABLE IF NOT EXISTS memory_salience (
            entry_id TEXT PRIMARY KEY,
            hit_count INTEGER NOT NULL DEFAULT 0,
            last_accessed TEXT DEFAULT NULL,
            salience_score REAL NOT NULL DEFAULT 0.0,
            verified_golden INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_memory_salience_golden ON memory_salience(verified_golden);
    """)
    cols = [r[1] for r in conn.execute("PRAGMA table_info(files)")]
    if "tzlocal" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN tzlocal INTEGER DEFAULT 0")
    for extra in ("valid_from", "valid_until", "source_event_time", "ingestion_time", "superseded_by", "agent_id", "run_id"):
        if extra not in cols:
            conn.execute(f"ALTER TABLE files ADD COLUMN {extra} TEXT DEFAULT ''")
    if "hit_count" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN hit_count INTEGER DEFAULT 0")
    if "last_accessed" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN last_accessed TEXT DEFAULT NULL")
    if "salience_score" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN salience_score REAL DEFAULT 0.0")
    if "verified_golden" not in cols:
        conn.execute("ALTER TABLE files ADD COLUMN verified_golden INTEGER DEFAULT 0")
    conn.commit()
    return conn


# --------------------------------------------------------------------------- parsing

def _norm_project(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", fold(name or ""))


def parse_tags(raw: str) -> List[str]:
    """Read safely serialized tags while supporting legacy unquoted lists."""
    try:
        tags = json.loads(raw or "[]")
    except ValueError:
        tags = None
    if isinstance(tags, list) and all(isinstance(tag, str) for tag in tags):
        return tags
    return [tag.strip().strip("'\"") for tag in (raw or "").strip("[]").split(",") if tag.strip()]


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
            key, value = m.group(1), m.group(2).strip()
            if key == "status" and key in fm:
                # Ambiguous approval metadata must never grant canonical status.
                fm[key] = "proposal"
                continue
            if value.startswith('"') and value.endswith('"'):
                try:
                    value = json.loads(value)
                except ValueError:
                    value = value.strip("'\"")
            else:
                value = value.strip("'\"")
            fm[key] = value
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
    vg_raw = fm.get("verified_golden", "") or fm.get("golden", "")
    verified_golden = 1 if str(vg_raw).strip().lower() in ("true", "1", "yes") else 0
    return {
        "project": project, "pnorm": _norm_project(project), "agent": agent, "session": session, "title": title,
        "date": date, "tzlocal": tzlocal, "rtype": rtype, "rid": fm.get("id", ""), "status": fm.get("status") or "proposal",
        "source_commit": fm.get("source_commit", ""), "tags": fm.get("tags", ""),
        "created_at": fm.get("created_at") or iso, "updated_at": fm.get("updated_at") or fm.get("created_at") or iso,
        "valid_from": fm.get("valid_from", ""), "valid_until": fm.get("valid_until", ""),
        "source_event_time": fm.get("source_event_time", ""), "ingestion_time": fm.get("ingestion_time", ""),
        "superseded_by": fm.get("superseded_by", ""), "agent_id": fm.get("agent_id", ""), "run_id": fm.get("run_id", ""),
        "verified_golden": verified_golden,
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

    # Preserve existing hit_count, last_accessed, salience_score, and verified_golden if already tracked
    old_file = conn.execute("SELECT hit_count, last_accessed, salience_score, verified_golden FROM files WHERE path = ?", (rel,)).fetchone()
    hit_count = old_file["hit_count"] if old_file and "hit_count" in old_file.keys() else 0
    last_accessed = old_file["last_accessed"] if old_file and "last_accessed" in old_file.keys() else None
    salience_score = old_file["salience_score"] if old_file and "salience_score" in old_file.keys() else 0.0
    if old_file and "verified_golden" in old_file.keys() and old_file["verified_golden"]:
        meta["verified_golden"] = 1

    old = conn.execute("SELECT rowid_ FROM chunk_map WHERE path = ?", (rel,)).fetchall()
    for r in old:
        conn.execute("DELETE FROM chunks WHERE rowid = ?", (r[0],))
    conn.execute("DELETE FROM chunk_map WHERE path = ?", (rel,))

    conn.execute(
        """INSERT OR REPLACE INTO files(path, mtime, size, project, pnorm, agent, session, title, date, rtype, rid,
           status, source_commit, tags, created_at, updated_at, tzlocal, valid_from, valid_until, source_event_time,
           ingestion_time, superseded_by, agent_id, run_id, verified_golden, hit_count, last_accessed, salience_score)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (rel, st.st_mtime, st.st_size, meta["project"], meta["pnorm"], meta["agent"], meta["session"], meta["title"],
         meta["date"], meta["rtype"], meta["rid"], meta["status"], meta["source_commit"], meta["tags"],
         meta["created_at"], meta["updated_at"], meta["tzlocal"], meta["valid_from"], meta["valid_until"],
         meta["source_event_time"], meta["ingestion_time"], meta["superseded_by"], meta["agent_id"], meta["run_id"],
         meta["verified_golden"], hit_count, last_accessed, salience_score),
    )

    # Wikilinks & Graph node/edge indexing
    node_id = meta["rid"] or rel.replace(os.sep, "/").removesuffix(".md")
    for (old_nid,) in conn.execute("SELECT id FROM memory_nodes WHERE path = ?", (rel,)).fetchall():
        if old_nid != node_id:
            conn.execute("DELETE FROM memory_edges WHERE source_id = ?", (old_nid,))
            conn.execute("DELETE FROM memory_nodes WHERE id = ?", (old_nid,))
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
                for (old_nid,) in conn.execute("SELECT id FROM memory_nodes WHERE path = ?", (gone,)).fetchall():
                    conn.execute("DELETE FROM memory_edges WHERE source_id = ?", (old_nid,))
                conn.execute("DELETE FROM memory_nodes WHERE path = ?", (gone,))
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


# --------------------------------------------------------------------------- salience & recall
HALF_LIFE_DAYS = 90.0


def calculate_decay(weight: float, elapsed_seconds: float, half_life_days: float = HALF_LIFE_DAYS) -> float:
    """Calculates exponential half-life decay: w * 2^(- dt_days / H)."""
    elapsed_days = max(0.0, float(elapsed_seconds)) / 86400.0
    return float(weight) * (2.0 ** (-elapsed_days / half_life_days))


def _parse_timestamp(ts_val: Any) -> datetime:
    """Robustly parse an ISO timestamp or date string to a timezone-aware UTC datetime."""
    if isinstance(ts_val, datetime):
        if ts_val.tzinfo is None:
            return ts_val.replace(tzinfo=timezone.utc)
        return ts_val
    s = str(ts_val or "").strip()
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                dt = datetime.strptime(s[:10], "%Y-%m-%d")
            except ValueError:
                dt = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def get_salience(entry_id: str, as_of: Optional[str | datetime] = None, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
    """Calculate and return salience statistics for an entry_id at evaluation time `as_of` (defaults to now).
    Formula: S(t) = sum(w_i * 2^(- (t - t_i) / H)) where H = 90 days.
    """
    eid = str(entry_id or "").strip()
    if not eid:
        return {
            "entry_id": "",
            "hit_count": 0,
            "last_accessed": None,
            "salience_score": 0.0,
            "verified_golden": False,
        }
    eid_norm = eid.replace("\\", "/")

    close_conn = False
    if conn is None:
        conn = connect()
        close_conn = True

    try:
        now_dt = _parse_timestamp(as_of) if as_of is not None else datetime.now(timezone.utc)
        alt_norm = eid_norm.replace("/", "\\")

        # 1. Fetch recall events for this entry_id
        rows = conn.execute(
            "SELECT timestamp, weight FROM recall_events WHERE entry_id = ? OR entry_id = ? ORDER BY timestamp ASC",
            (eid_norm, alt_norm)
        ).fetchall()

        hit_count = len(rows)
        last_accessed = rows[-1]["timestamp"] if rows else None

        # 2. Compute decayed salience score S(t) = sum(w_i * 2^(- (t - t_i) / H))
        salience_score = 0.0
        for r in rows:
            t_i = _parse_timestamp(r["timestamp"])
            dt_sec = (now_dt - t_i).total_seconds()
            if dt_sec < 0.0:
                dt_sec = 0.0
            salience_score += calculate_decay(r["weight"], dt_sec, half_life_days=HALF_LIFE_DAYS)

        # 3. Check verified_golden
        is_golden = False
        ms = conn.execute(
            "SELECT verified_golden FROM memory_salience WHERE entry_id = ? OR entry_id = ?",
            (eid_norm, alt_norm)
        ).fetchone()
        if ms and ms["verified_golden"]:
            is_golden = True

        base_ref = eid_norm.split("#")[0] if "#" in eid_norm else eid_norm
        if not is_golden:
            f_row = conn.execute(
                "SELECT verified_golden FROM files WHERE path = ? OR rid = ? OR replace(path, '\\', '/') = ?",
                (base_ref, base_ref, base_ref)
            ).fetchone()
            if f_row and f_row["verified_golden"]:
                is_golden = True

        if not is_golden and "#" in eid_norm:
            ms_base = conn.execute(
                "SELECT verified_golden FROM memory_salience WHERE entry_id = ?",
                (base_ref,)
            ).fetchone()
            if ms_base and ms_base["verified_golden"]:
                is_golden = True

        # Cache in memory_salience table
        try:
            with conn:
                conn.execute(
                    """INSERT INTO memory_salience(entry_id, hit_count, last_accessed, salience_score, verified_golden)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(entry_id) DO UPDATE SET
                           hit_count = excluded.hit_count,
                           last_accessed = excluded.last_accessed,
                           salience_score = excluded.salience_score,
                           verified_golden = MAX(memory_salience.verified_golden, excluded.verified_golden)""",
                    (eid_norm, hit_count, last_accessed, round(salience_score, 6), 1 if is_golden else 0)
                )
        except sqlite3.OperationalError:
            pass

        return {
            "entry_id": eid_norm,
            "hit_count": hit_count,
            "last_accessed": last_accessed,
            "salience_score": round(salience_score, 6),
            "verified_golden": is_golden,
        }
    finally:
        if close_conn:
            conn.close()


def record_recall_event(entry_id: str, weight: float = 1.0, timestamp: Optional[str | datetime] = None) -> Dict[str, Any]:
    """Records a recall event for the specified memory entry / chunk, updating hit_count, last_accessed,
    and recalculating the exponential decay salience score S(t)."""
    eid = str(entry_id or "").strip()
    if not eid:
        return {
            "entry_id": "",
            "hit_count": 0,
            "last_accessed": None,
            "salience_score": 0.0,
            "verified_golden": False,
        }
    eid_norm = eid.replace("\\", "/")

    if timestamp is None:
        event_dt = datetime.now(timezone.utc)
        event_ts = event_dt.isoformat()
    elif isinstance(timestamp, datetime):
        event_dt = timestamp if timestamp.tzinfo is not None else timestamp.replace(tzinfo=timezone.utc)
        event_ts = event_dt.isoformat()
    else:
        event_dt = _parse_timestamp(timestamp)
        event_ts = event_dt.isoformat()

    conn = connect()
    try:
        with conn:
            conn.execute(
                "INSERT INTO recall_events(entry_id, timestamp, weight) VALUES (?, ?, ?)",
                (eid_norm, event_ts, float(weight))
            )
            base_ref = eid_norm.split("#")[0] if "#" in eid_norm else None
            if base_ref and base_ref != eid_norm:
                conn.execute(
                    "INSERT INTO recall_events(entry_id, timestamp, weight) VALUES (?, ?, ?)",
                    (base_ref, event_ts, float(weight))
                )

        sal = get_salience(eid_norm, as_of=event_dt, conn=conn)

        ref_to_sync = base_ref or eid_norm
        try:
            with conn:
                conn.execute(
                    "UPDATE files SET hit_count = ?, last_accessed = ?, salience_score = ? WHERE path = ? OR rid = ? OR replace(path, '\\', '/') = ?",
                    (sal["hit_count"], sal["last_accessed"], sal["salience_score"], ref_to_sync, ref_to_sync, ref_to_sync)
                )
        except sqlite3.OperationalError:
            pass

        return sal
    finally:
        conn.close()


def set_verified_golden(entry_id: str, golden: bool = True) -> bool:
    """Mark or unmark a memory entry or file as verified golden."""
    eid = str(entry_id or "").strip()
    if not eid:
        return False
    eid_norm = eid.replace("\\", "/")
    val = 1 if golden else 0
    conn = connect()
    try:
        with conn:
            conn.execute(
                """INSERT INTO memory_salience(entry_id, hit_count, last_accessed, salience_score, verified_golden)
                   VALUES (?, 0, NULL, 0.0, ?)
                   ON CONFLICT(entry_id) DO UPDATE SET verified_golden = ?""",
                (eid_norm, val, val)
            )
            base_ref = eid_norm.split("#")[0] if "#" in eid_norm else eid_norm
            conn.execute(
                "UPDATE files SET verified_golden = ? WHERE path = ? OR rid = ? OR replace(path, '\\', '/') = ?",
                (val, base_ref, base_ref, base_ref)
            )
        return True
    finally:
        conn.close()


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

        import math
        if is_time_sort:
            all_rows = list(and_rows) + list(or_rows)
            def time_key(r: sqlite3.Row) -> tuple[str, str, int]:
                return (r["date"] or "", r["ts"] or "", r["line"] or 0)
            all_rows.sort(key=time_key, reverse=(ob == "time_desc"))
            kw = [dict(r) for r in all_rows]
        elif ob == "salience":
            all_rows = list(and_rows)
            seen_ids = {(r["path"], r["line"]) for r in and_rows}
            for r in or_rows:
                if (r["path"], r["line"]) not in seen_ids:
                    all_rows.append(r)

            part: List[Tuple[int, float, float, Dict[str, Any]]] = []
            for r in all_rows:
                f = file_of(r["path"])
                if f is None:
                    continue
                cid = f"{r['path'].replace(os.sep, '/')}#{r['line']}"
                sal = get_salience(cid, as_of=as_of, conn=conn)
                is_golden = bool(sal["verified_golden"] or (f["verified_golden"] if "verified_golden" in f.keys() else False))
                golden_prio = 0 if is_golden else 1
                part.append((golden_prio, -sal["salience_score"], r["rank"], dict(r)))
            part.sort(key=lambda x: (x[0], x[1], x[2]))
            kw = [d for _, _, _, d in part]
        else:
            # relevance (default BM25 + salience boost, with verified_golden ALWAYS strictly first)
            for block in (and_rows, or_rows):
                part_rel: List[Tuple[int, float, Dict[str, Any]]] = []
                for r in block:
                    f = file_of(r["path"])
                    if f is None:
                        continue
                    penalty = 1.5 if f["rtype"] == "readme" else 0.0
                    cid = f"{r['path'].replace(os.sep, '/')}#{r['line']}"
                    sal = get_salience(cid, as_of=as_of, conn=conn)
                    is_golden = bool(sal["verified_golden"] or (f["verified_golden"] if "verified_golden" in f.keys() else False))
                    golden_prio = 0 if is_golden else 1
                    sal_boost = math.log1p(max(0.0, sal["salience_score"])) * 0.5
                    effective_rank = r["rank"] + penalty - sal_boost
                    part_rel.append((golden_prio, effective_rank, dict(r)))
                part_rel.sort(key=lambda x: (x[0], x[1]))
                kw.extend(d for _, _, d in part_rel)

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

            cid = f"{r['path'].replace(os.sep, '/')}#{r['line']}"
            res_item = {
                "id": cid,
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

            # Record recall event for called / selected memory search hit
            sal = record_recall_event(cid, weight=1.0)
            res_item["hit_count"] = sal["hit_count"]
            res_item["last_accessed"] = sal["last_accessed"]
            res_item["salience_score"] = sal["salience_score"]
            res_item["verified_golden"] = sal["verified_golden"]

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

    entry_id = f["rid"] or f"{f['path'].replace(os.sep, '/')}#{start}"
    sal = get_salience(entry_id, conn=conn)
    is_golden = bool(sal["verified_golden"] or (f["verified_golden"] if "verified_golden" in f.keys() else False))
    out = {
        "id": entry_id,
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
        "hit_count": sal["hit_count"],
        "last_accessed": sal["last_accessed"],
        "salience_score": sal["salience_score"],
        "verified_golden": is_golden,
    }
    if extra:
        out.update(extra)
    return out


def _finish_get(rec: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not rec:
        return None
    sal = record_recall_event(rec["id"], weight=1.0)
    rec["hit_count"] = sal["hit_count"]
    rec["last_accessed"] = sal["last_accessed"]
    rec["salience_score"] = sal["salience_score"]
    rec["verified_golden"] = sal["verified_golden"]
    return rec


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
            return _finish_get(_record(conn, f, 1, 10 ** 6))

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
                return _finish_get(_record(conn, f, s, e))

            c = conn.execute(
                "SELECT line, endline FROM chunks WHERE path = ? AND line <= ? AND endline >= ? LIMIT 1",
                (f["path"], line, line)
            ).fetchone()
            start = c["line"] if c else max(1, line - 5)
            end = c["endline"] if c else line + 60
            if surround:
                start = max(1, start - surround)
                end = end + surround
            return _finish_get(_record(conn, f, start, end))

        f = _file_row(conn, rid)
        if f:
            return _finish_get(_record(conn, f, 1, 10 ** 6))

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
        return _finish_get(_record(conn, newest, 1, 10 ** 6, extra))
    finally:
        conn.close()
