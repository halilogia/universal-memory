"""Token-lean MCP output for memory_search / memory_get.

Search hits used to carry ~25 fields (path, title, salience, hit_count...) pretty-printed with indent=2,
about 1k tokens per hit. Agents only need: where (id), who/when, and the matched text.
Everything dropped here is still reachable through memory_get(id) or `verbose: true`.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

SNIPPET_MAX = 320

# Fields worth keeping only when they carry a signal.
_SIGNAL_FIELDS = ("stale_warning", "verified_golden", "superseded_by")


def _short(text: Any, limit: int) -> str:
    s = " ".join(str(text or "").split())
    return s if len(s) <= limit else s[: limit - 1] + "…"


def compact_hit(hit: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"id": hit.get("id", "")}
    when = hit.get("when")
    if when:
        out["when"] = when
    speaker = hit.get("speaker") or ""
    # Long "speaker" values are section headings, already visible in the snippet.
    if speaker and len(speaker) <= 40:
        out["speaker"] = speaker
    if hit.get("agent"):
        out["agent"] = hit["agent"]
    if hit.get("status") and hit["status"] not in ("canonical", "proposal"):
        out["status"] = hit["status"]
    for key in _SIGNAL_FIELDS:
        if hit.get(key):
            out[key] = hit[key]
    out["snippet"] = _short(hit.get("snippet"), SNIPPET_MAX)
    if hit.get("context"):
        out["context"] = hit["context"]
    return out


def compact_search(result: Any) -> Any:
    if isinstance(result, list):
        return [compact_hit(h) if isinstance(h, dict) else h for h in result]
    return result


def compact_record(record: Any) -> Any:
    """Drop empty/bookkeeping fields from memory_get; keep content and provenance."""
    if not isinstance(record, dict):
        return record
    drop = {"hit_count", "last_accessed", "salience_score", "filepath", "created_at", "updated_at"}
    out = {}
    for key, value in record.items():
        if key in drop or value in ("", None, [], {}):
            continue
        if key == "relations" and isinstance(value, dict) and not any(value.values()):
            continue
        if key == "validity" and isinstance(value, dict) and value.get("status") == "unknown":
            continue
        out[key] = value
    return out


def dumps(obj: Any, verbose: bool = False) -> str:
    if verbose:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def render_search(result: Any, verbose: bool = False) -> str:
    return dumps(result if verbose else compact_search(result), verbose)


def render_record(record: Any, verbose: bool = False) -> str:
    return dumps(record if verbose else compact_record(record), verbose)


__all__: List[str] = ["compact_hit", "compact_search", "compact_record", "render_search", "render_record"]
