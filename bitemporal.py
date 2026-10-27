"""
Bi-temporal knowledge model (Graphiti-style) on top of Markdown frontmatter.

Two time axes per record:
  * valid time        -> ``valid_from`` .. ``valid_until``  (when the fact is true in the world / for the project)
  * transaction time  -> ``ingestion_time``                 (when the memory system learned it)
  * ``source_event_time`` = when the originating event happened (e.g. the chat message time).
A record is never deleted when it is replaced: ``valid_until`` is closed, ``status: superseded`` is set and
``superseded_by: <new id>`` links the timeline. Records without these fields (chat transcripts, legacy notes) are
treated as valid forever.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Dict, Optional

TEMPORAL_FIELDS = ("valid_from", "valid_until", "source_event_time", "ingestion_time", "superseded_by")


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


def parse_ts(value: Optional[str]) -> Optional[datetime]:
    """Parse 'YYYY-MM-DD' or ISO datetime (naive/aware) into a naive datetime; empty/invalid -> None."""
    v = (value or "").strip().strip("'\"")
    if not v or v.lower() in ("null", "none", "~"):
        return None
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt


def is_valid_at(valid_from: Optional[str], valid_until: Optional[str], as_of: Optional[str] = None) -> bool:
    """True when ``as_of`` (default: now) lies in [valid_from, valid_until). Missing bounds are open."""
    at = parse_ts(as_of) or datetime.now()
    start, end = parse_ts(valid_from), parse_ts(valid_until)
    if start and at < start:
        return False
    if end and at >= end:
        return False
    return True


def record_is_valid(row: Any, as_of: Optional[str] = None) -> bool:
    """``row`` is a ``files`` row / dict. Superseded records are valid only for as_of values before their end."""
    get = row.get if isinstance(row, dict) else (lambda k, d=None: row[k] if k in row.keys() else d)
    if not get("valid_until") and (get("status") or "").lower() in ("superseded", "invalidated"):
        # closed without an explicit end (hand-edited): only visible when explicitly asking for history
        return False
    if not get("valid_until") and get("superseded_by"):
        return False
    return is_valid_at(get("valid_from"), get("valid_until"), as_of)


def set_frontmatter(path: str, updates: Dict[str, str]) -> None:
    """Surgically set/insert ``key: value`` lines inside the leading ``---`` block; body untouched."""
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if not text.startswith("---"):
        raise ValueError(f"No frontmatter in {path}")
    end = text.find("\n---", 3)
    if end < 0:
        raise ValueError(f"Unterminated frontmatter in {path}")
    head, tail = text[:end], text[end:]
    for key, value in updates.items():
        line = f"{key}: {value}"
        head, n = re.subn(rf"^{re.escape(key)}:.*$", lambda _m: line, head, count=1, flags=re.MULTILINE)
        if n == 0:
            head += "\n" + line
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(head + tail)
    os.replace(tmp, path)


def append_edge(path: str, relation: str, target_id: str) -> None:
    """Append a typed relation line (``- supersedes: [[id]]``) to the note body (idempotent)."""
    line = f"- {relation}: [[{target_id}]]"
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    if line in text:
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.rstrip("\n") + "\n\n" + line + "\n")


def supersede(old_id: str, new_id: str, when: Optional[str] = None) -> Dict[str, Any]:
    """Close ``old_id``'s validity window at ``when`` (default now) and link it to ``new_id``. Nothing is deleted."""
    import memory_engine
    old = memory_engine.memory_get(old_id)
    new = memory_engine.memory_get(new_id)
    if not old:
        return {"success": False, "error": f"Record not found: {old_id}"}
    if not new:
        return {"success": False, "error": f"Record not found: {new_id}"}
    old_key, new_key = old["id"], new["id"]
    if old_key == new_key:
        return {"success": False, "error": "A record cannot supersede itself"}
    if old.get("superseded_by"):
        return {"success": False, "error": f"'{old_key}' is already superseded by '{old['superseded_by']}'"}
    when = when or now_iso()
    set_frontmatter(old["filepath"], {"valid_until": when, "superseded_by": new_key, "status": "superseded"})
    append_edge(new["filepath"], "supersedes", old_key)
    memory_engine.sync_vault()
    return {"success": True, "superseded": old_key, "superseded_by": new_key, "valid_until": when}
