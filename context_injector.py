"""
Context injector for OpenCode / local models.

Builds ONE compact ``--context`` pack from the memory vault: only canonical, still-valid (never invalidated/superseded)
conventions, decisions, lessons (incl. negative knowledge) plus open tasks of the latest handoff, ranked by relevance
to the query and trimmed to a character budget.

CLI:   python context_injector.py --project GravityGuard --query "logging" --max-chars 3000 [--as-of 2026-09-01] [--out ctx.md]
Code:  inject_prompt(prompt, project) -> "<context pack>\\n\\n<prompt>"
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

import memory_index
from bitemporal import record_is_valid

TYPE_WEIGHT = {"convention": 1.0, "decision": 0.9, "lesson": 0.8}
SECTIONS = [
    ("convention", "KURALLAR"),
    ("decision", "KARARLAR"),
    ("negative", "DENENDİ, ÇALIŞMADI (tekrarlama)"),
    ("lesson", "DERSLER"),
]
_FM = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_TASK = re.compile(r"^\s*-\s*\[ \]\s*(.+)$", re.MULTILINE)


def _body(rel: str) -> str:
    try:
        with open(os.path.join(memory_index._vault_root(), rel), "r", encoding="utf-8", errors="replace") as f:
            text = _FM.sub("", f.read(), count=1)
    except OSError:
        return ""
    text = re.sub(r"^#.*$", "", text, flags=re.MULTILINE)             # headings (title is shown separately)
    text = re.sub(r"^\s*-\s*(?:supersedes|contradicts):.*$", "", text, flags=re.MULTILINE)
    return " ".join(text.split())


def _squeeze(text: str, width: int) -> str:
    return text if len(text) <= width else text[: width - 1].rstrip() + "…"


def _score(row: Any, body: str, qtok: set, newest_rank: int) -> float:
    weight = TYPE_WEIGHT.get(row["rtype"], 0.5)
    if "negative" in (row["tags"] or ""):
        weight += 0.3
    overlap = 0.0
    if qtok:
        doc = set(re.findall(r"\w+", memory_index.fold(row["title"] + " " + body)))
        overlap = len(qtok & doc) / len(qtok)
    recency = 1.0 / (1 + newest_rank)
    return weight + 2.0 * overlap + 0.2 * recency


def build_context(project: str, query: str = "", max_chars: int = 3000, as_of: Optional[str] = None,
                  agent_id: str = "", include_proposals: bool = False, card_chars: int = 280) -> Dict[str, Any]:
    """Return ``{"text": str, "cards": [...], "chars": int}``; text never exceeds ``max_chars``."""
    memory_index.ensure_fresh()
    pnorm = memory_index._norm_project(project)
    statuses = {"canonical"} | ({"proposal"} if include_proposals else set())
    conn = memory_index.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM files WHERE (pnorm = ? OR pnorm = 'global') AND rtype IN ('decision','lesson','convention','handoff') "
            "ORDER BY date DESC, updated_at DESC", (pnorm,)).fetchall()
    finally:
        conn.close()

    qtok = {t for t in re.findall(r"\w+", memory_index.fold(query)) if len(t) >= 3 and t not in memory_index._STOP}
    cards: List[Dict[str, Any]] = []
    latest_handoff: Optional[Any] = None
    for rank, r in enumerate(rows):
        if (r["status"] or "").lower() not in statuses or not record_is_valid(r, as_of):
            continue
        if agent_id and r["agent_id"] and r["agent_id"] != agent_id:
            continue                                                   # scoped to another agent
        if r["rtype"] == "handoff":
            latest_handoff = latest_handoff or r
            continue
        body = _body(r["path"])
        kind = "negative" if "negative" in (r["tags"] or "") else r["rtype"]
        cards.append({
            "id": r["rid"] or r["path"].replace(os.sep, "/").removesuffix(".md"),
            "kind": kind, "title": r["title"], "text": _squeeze(body, card_chars),
            "score": round(_score(r, body, qtok, rank), 3),
        })
    cards.sort(key=lambda c: c["score"], reverse=True)

    tasks: List[str] = []
    if latest_handoff is not None:
        tasks = [t.strip() for t in _TASK.findall(_body_raw(latest_handoff["path"]))][:8]

    header = f"# HAFIZA BAĞLAMI — {project}" + (f" (as_of {as_of})" if as_of else "")
    picked: List[Dict[str, Any]] = []
    used = len(header) + 1
    tasks_block = ""
    if tasks:
        tasks_block = "\n## AÇIK İŞLER\n" + "\n".join(f"- [ ] {_squeeze(t, 160)}" for t in tasks)
        used += len(tasks_block) + 1
    for c in cards:
        if qtok and c["score"] < TYPE_WEIGHT.get(c["kind"], 0.5) + 0.01 and len(picked) >= 3:
            continue                                                   # unrelated to the query once we have a base
        line = f"- {c['title']}: {c['text']}\n" if c["text"] and c["text"] != c["title"] else f"- {c['title']}\n"
        if used + len(line) + 24 > max_chars:
            continue
        picked.append(c)
        used += len(line)

    out = [header]
    for kind, label in SECTIONS:
        items = [c for c in picked if c["kind"] == kind]
        if items:
            out.append(f"\n## {label}")
            out.extend(f"- {c['title']}: {c['text']}" if c["text"] and c["text"] != c["title"] else f"- {c['title']}" for c in items)
    if tasks_block:
        out.append(tasks_block)
    text = "\n".join(out)
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    return {"text": text, "cards": picked, "chars": len(text)}


def _body_raw(rel: str) -> str:
    try:
        with open(os.path.join(memory_index._vault_root(), rel), "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def inject_prompt(prompt: str, project: str, query: str = "", max_chars: int = 3000, **kw: Any) -> str:
    """Prefix ``prompt`` with the context pack (for ``opencode run`` / any local model)."""
    pack = build_context(project, query or prompt, max_chars=max_chars, **kw)["text"]
    return f"{pack}\n\n---\n{prompt}"


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Compact, validity-filtered memory context pack")
    ap.add_argument("--project", required=True)
    ap.add_argument("--query", default="")
    ap.add_argument("--max-chars", type=int, default=3000)
    ap.add_argument("--as-of", default=None, help="time-travel: ISO date/time")
    ap.add_argument("--agent-id", default="")
    ap.add_argument("--proposals", action="store_true", help="also include uncommitted proposals")
    ap.add_argument("--out", default=None, help="write pack to file instead of stdout")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = build_context(a.project, a.query, a.max_chars, a.as_of, a.agent_id, a.proposals)
    payload = json.dumps(res, ensure_ascii=False, indent=2) if a.json else res["text"]
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(payload)
    else:
        sys.stdout.buffer.write((payload + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
