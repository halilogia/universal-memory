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
from collections import Counter
from math import log1p
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
_VERIFICATION_WORDS = {"dogrulama", "verification", "review", "kural", "test"}
VERIFICATION_TEMPLATE = (
    "\n\n## Evidence Checklist\n"
    "1. Test Exit Code: command, exit code, passed/failed counts.\n"
    "2. Build Integrity: build command, exit code, artifact.\n"
    "3. Visual/Viewport Check: viewport sizes, screenshot, observed result.\n"
    "4. Console Zero Error: inspected logs, error count.\n"
    "Mark unperformed checks as NOT RUN; explain N/A."
)


def _tokens(text: str) -> list[str]:
    return re.findall(r"\w+", memory_index.fold(text))


def _negative(row: Any) -> bool:
    return row["rtype"] == "lesson" and "negative" in memory_index.parse_tags(row["tags"] or "[]")


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


def _score(row: Any, body: str, qtok: set[str], newest_rank: int) -> float:
    """Reward coverage and saturated frequency; title occurrences count threefold."""
    weight = TYPE_WEIGHT.get(row["rtype"], 0.5)
    title_counts = Counter(_tokens(row["title"] or ""))
    body_counts = Counter(_tokens(body))
    overlap = 0.0
    frequency = 0.0
    if qtok:
        overlap = len(qtok & (title_counts.keys() | body_counts.keys())) / len(qtok)
        frequency = sum(min(3 * title_counts[t] + body_counts[t], 12) / 12 for t in qtok) / len(qtok)
    negative = (0.15 + 0.35 * overlap) if _negative(row) else 0.0
    recency = 1.0 / (1.0 + log1p(max(0, newest_rank)))
    return weight + 3.0 * overlap + frequency + negative + 0.25 * recency


def build_context(project: str, query: str = "", max_chars: int = 3000, as_of: Optional[str] = None,
                  agent_id: str = "", include_proposals: bool = False, card_chars: int = 280,
                  include_global: bool = True, inject_verification_template: bool = False) -> Dict[str, Any]:
    """Build a bounded pack. Global mode adds global and query-matching foreign cards.

    ``all``/``*`` select every project, even without a query. Named projects retain
    only their own latest handoff. Verification keywords always enable the checklist.
    """
    if max_chars < 0 or card_chars < 1:
        raise ValueError("max_chars must be nonnegative and card_chars must be positive")
    verification = inject_verification_template or bool(_VERIFICATION_WORDS & set(_tokens(query)))
    suffix = VERIFICATION_TEMPLATE if verification else ""
    if len(suffix) > max_chars:
        raise ValueError(f"max_chars must be at least {len(suffix)} for the evidence checklist")
    content_budget = max_chars - len(suffix)
    memory_index.ensure_fresh()
    pnorm = memory_index._norm_project(project)
    all_projects = project.strip().lower() in {"all", "*"}
    statuses = {"canonical"} | ({"proposal"} if include_proposals else set())
    conn = memory_index.connect()
    try:
        rows = conn.execute(
            "SELECT * FROM files WHERE (? OR pnorm = ?) AND rtype IN ('decision','lesson','convention','handoff') "
            "ORDER BY date DESC, updated_at DESC, path ASC", (all_projects or include_global, pnorm)).fetchall()
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
            if not all_projects and r["pnorm"] == pnorm:
                latest_handoff = latest_handoff or r
            continue
        body = _body(r["path"])
        if not all_projects and r["pnorm"] not in {pnorm, "global"}:
            if not qtok.intersection(_tokens((r["title"] or "") + " " + body)):
                continue
        kind = "negative" if _negative(r) else r["rtype"]
        cards.append({
            "id": r["rid"] or r["path"].replace(os.sep, "/").removesuffix(".md"),
            "kind": kind, "title": r["title"], "text": _squeeze(body, card_chars),
            "project": r["project"],
            "score": round(_score(r, body, qtok, rank), 3),
        })
    cards.sort(key=lambda c: c["score"], reverse=True)

    tasks: List[str] = []
    if latest_handoff is not None:
        tasks = [t.strip() for t in _TASK.findall(_body_raw(latest_handoff["path"]))][:8]

    header = f"# HAFIZA BAĞLAMI — {project}" + (f" (as_of {as_of})" if as_of else "")
    picked: List[Dict[str, Any]] = []
    used = len(header)
    section_kinds: set[str] = set()
    tasks_block = ""
    if tasks:
        tasks_block = "\n## AÇIK İŞLER\n" + "\n".join(f"- [ ] {_squeeze(t, 160)}" for t in tasks)
        if used + len(tasks_block) + 1 <= content_budget:
            used += len(tasks_block) + 1
        else:
            tasks_block = ""
    for c in cards:
        line = f"- {c['title']}: {c['text']}\n" if c["text"] and c["text"] != c["title"] else f"- {c['title']}\n"
        section_cost = 0 if c["kind"] in section_kinds else len("\n\n## " + dict(SECTIONS)[c["kind"]])
        if used + len(line) + section_cost > content_budget:
            continue
        picked.append(c)
        used += len(line) + section_cost
        section_kinds.add(c["kind"])

    out = [header]
    for kind, label in SECTIONS:
        items = [c for c in picked if c["kind"] == kind]
        if items:
            out.append(f"\n## {label}")
            out.extend(f"- {c['title']}: {c['text']}" if c["text"] and c["text"] != c["title"] else f"- {c['title']}" for c in items)
    if tasks_block:
        out.append(tasks_block)
    text = "\n".join(out)
    if len(text) > content_budget:
        text = _squeeze(text, content_budget) if content_budget else ""
    text += suffix
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
    ap.add_argument("--no-global", action="store_true", help="restrict a named project to its own records")
    ap.add_argument("--inject-verification-template", action="store_true", help="always append the evidence checklist")
    ap.add_argument("--out", default=None, help="write pack to file instead of stdout")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    res = build_context(a.project, a.query, a.max_chars, a.as_of, a.agent_id, a.proposals,
                        include_global=not a.no_global, inject_verification_template=a.inject_verification_template)
    payload = json.dumps(res, ensure_ascii=False, indent=2) if a.json else res["text"]
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(payload)
    else:
        sys.stdout.buffer.write((payload + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
