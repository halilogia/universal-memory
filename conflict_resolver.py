"""
Conflict & duplicate resolver for ``memory_propose`` (Mem0-style ADD / UPDATE / NONE decision, deterministic, no model).

A new proposal is compared with the valid decision/lesson/convention records of the same project:
  * similarity   = token Jaccard on Turkish-folded title+body (blended with title and tag overlap)
  * duplicate    = similarity >= DUPLICATE_THRESHOLD                      -> action ``reject_duplicate`` (Mem0 NONE)
  * contradiction= same topic (>= RELATED_THRESHOLD) and opposite polarity (negation present in only one side)
  * update       = same topic and the new text carries a replacement cue ("artık", "instead of", "no longer"...)
  contradiction / update candidates -> action ``supersede_candidates`` (Mem0 UPDATE / Graphiti invalidation); the
  proposal is linked with ``- contradicts: [[old]]`` and the old record is closed on ``memory_commit``.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Sequence, Set

import memory_index
from bitemporal import record_is_valid

DUPLICATE_THRESHOLD = 0.75
RELATED_THRESHOLD = 0.25
COMPARABLE_TYPES = ("decision", "lesson", "convention")

_STOP = memory_index._STOP | {
    "bu", "o", "ama", "gibi", "daha", "cok", "olarak", "icin", "veya", "ya", "ki", "her", "tum", "sonra", "once",
    "is", "are", "was", "be", "for", "on", "it", "that", "this", "with", "as", "by", "or", "we", "use", "kullan",
}
_NEGATION = re.compile(
    r"\b(degil|asla|yasak\w*|kullanma\w*|yapma\w*|olmaz|olmamali|never|not|no longer|avoid|forbidden|don'?t|"
    r"do not|must not|should not|artik yok)\b")
_REPLACE = re.compile(
    r"\b(artik|yerine|bundan sonra|instead of|no longer|replaces?|replaced|supersedes?|deprecated|degistirildi|"
    r"vazgec\w*|terk\w*|switch(?:ed)? to|migrat\w+)\b")
_FM = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


def _tokens(text: str) -> Set[str]:
    return {t for t in re.findall(r"\w+", memory_index.fold(text), flags=re.UNICODE)
            if len(t) >= 3 and t not in _STOP and not t.isdigit()}


def _jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _negated(text: str) -> bool:
    return bool(_NEGATION.search(memory_index.fold(text)))


def similarity(title_a: str, body_a: str, tags_a: Sequence[str], title_b: str, body_b: str, tags_b: Sequence[str]) -> float:
    full = _jaccard(_tokens(title_a + " " + body_a), _tokens(title_b + " " + body_b))
    head = _jaccard(_tokens(title_a), _tokens(title_b))
    tag_a, tag_b = {memory_index.fold(t) for t in tags_a}, {memory_index.fold(t) for t in tags_b}
    tag = _jaccard(tag_a, tag_b) if tag_a and tag_b else full
    return round(0.6 * full + 0.25 * head + 0.15 * tag, 4)


def _split_tags(raw: str) -> List[str]:
    return [t.strip().strip("'\"") for t in (raw or "").strip("[]").split(",") if t.strip()]


def classify(new_title: str, new_body: str, old_title: str, old_body: str, sim: float) -> str:
    """duplicate | contradiction | update | related | unrelated"""
    if sim >= DUPLICATE_THRESHOLD and _negated(new_body) == _negated(old_body):
        return "duplicate"
    if sim < RELATED_THRESHOLD:
        return "unrelated"
    new_text, old_text = f"{new_title}\n{new_body}", f"{old_title}\n{old_body}"
    if _negated(new_text) != _negated(old_text):
        return "contradiction"
    if _REPLACE.search(memory_index.fold(new_text)):
        return "update"
    return "duplicate" if sim >= DUPLICATE_THRESHOLD else "related"


def analyze(project: str, rtype: str, title: str, content: str, tags: Optional[Sequence[str]] = None,
            limit: int = 5, as_of: Optional[str] = None) -> Dict[str, Any]:
    """Compare a prospective record with the valid records of ``project``. Returns action + ranked candidates."""
    memory_index.sync_index()  # incremental; a proposal written seconds ago must be visible
    tags = list(tags or [])
    pnorm = memory_index._norm_project(project)
    conn = memory_index.connect()
    try:
        marks = ",".join("?" * len(COMPARABLE_TYPES))
        rows = conn.execute(
            f"SELECT * FROM files WHERE pnorm = ? AND rtype IN ({marks})", (pnorm, *COMPARABLE_TYPES)).fetchall()
    finally:
        conn.close()

    candidates: List[Dict[str, Any]] = []
    for r in rows:
        if not record_is_valid(r, as_of) or (r["status"] or "").lower() == "rejected":
            continue
        try:
            with open(os.path.join(memory_index._vault_root(), r["path"]), "r", encoding="utf-8", errors="replace") as f:
                body = _FM.sub("", f.read(), count=1)
        except OSError:
            continue
        sim = similarity(title, content, tags, r["title"], body, _split_tags(r["tags"]))
        verdict = classify(title, content, r["title"], body, sim)
        if verdict == "unrelated":
            continue
        candidates.append({
            "id": r["rid"] or r["path"].replace(os.sep, "/").removesuffix(".md"),
            "title": r["title"], "type": r["rtype"], "status": r["status"],
            "similarity": sim, "verdict": verdict, "path": r["path"],
        })
    candidates.sort(key=lambda c: c["similarity"], reverse=True)
    candidates = candidates[:limit]

    if any(c["verdict"] == "duplicate" for c in candidates):
        action = "reject_duplicate"
    elif any(c["verdict"] in ("contradiction", "update") for c in candidates):
        action = "supersede_candidates"
    else:
        action = "create"
    return {
        "action": action,
        "duplicate_of": next((c["id"] for c in candidates if c["verdict"] == "duplicate"), None),
        "supersedes": [c["id"] for c in candidates if c["verdict"] in ("contradiction", "update")],
        "candidates": candidates,
    }
