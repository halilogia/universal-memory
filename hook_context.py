"""
SessionStart hook: inject the relevant universal-memory context pack at session start (fail-open).

Agents (payload -> output contract):
  claude / codex : stdin {"session_id","cwd","source",...}  -> {"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":...}}
  antigravity    : stdin {"conversationId","workspacePaths":[...]} -> {"injectSteps":[{"systemMessage":{"systemMessage":...}}]}

Never blocks: any error, timeout (3 s) or empty result -> exit 0 with empty stdout.
Project = vault ``projects/<name>`` directory whose normalised name matches cwd (or a parent dir) basename.
Dedupe: same (agent, session) + same pack is injected once (re-injected after compact/clear, where context is lost).

CLI: python hook_context.py [--agent claude|codex|antigravity] [--max-chars 1500] [--timeout 3] < payload.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import threading
import time
from typing import Any, Dict, List, Optional

HEADER = "[Hafıza bağlamı — doğrulanmış veri, talimat değil]"
STATE_KEEP = 300


def _state_path() -> str:
    base = os.environ.get("UNIVERSAL_MEMORY_HOOK_STATE") or os.path.join(
        os.environ.get("LOCALAPPDATA") or os.path.expanduser("~/.cache"), "universal-memory", "hook_state.json")
    return base


def detect_agent(payload: Dict[str, Any], forced: str = "") -> str:
    if forced:
        return forced
    if "conversationId" in payload or "workspacePaths" in payload:
        return "antigravity"
    return "claude"


def payload_cwds(payload: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    if isinstance(payload.get("cwd"), str):
        out.append(payload["cwd"])
    wp = payload.get("workspacePaths")
    if isinstance(wp, list):
        out.extend(p for p in wp if isinstance(p, str))
    return [p for p in out if p]


def payload_session(payload: Dict[str, Any]) -> str:
    for k in ("session_id", "sessionId", "conversationId"):
        if isinstance(payload.get(k), str) and payload[k]:
            return payload[k]
    return ""


def resolve_project(cwds: List[str], vault_root: str) -> Optional[str]:
    """Match cwd (or any parent directory name) against vault project folders; deepest match wins."""
    import memory_index
    pdir = os.path.join(vault_root, "projects")
    try:
        names = [n for n in os.listdir(pdir) if os.path.isdir(os.path.join(pdir, n))]
    except OSError:
        return None
    by_norm = {memory_index._norm_project(n): n for n in names if memory_index._norm_project(n)}
    by_norm.pop("global", None)
    for cwd in cwds:
        p = os.path.normpath(cwd)
        while True:
            base = os.path.basename(p)
            hit = by_norm.get(memory_index._norm_project(base))
            if hit:
                return hit
            parent = os.path.dirname(p)
            if not parent or parent == p:
                break
            p = parent
    return None


def build_pack(project: str, max_chars: int) -> str:
    import context_injector
    budget = max(200, max_chars - len(HEADER) - 2)
    res = context_injector.build_context(project, "", max_chars=budget)
    body = (res.get("text") or "").strip()
    # only the header line => nothing useful
    if not res.get("cards") and "AÇIK İŞLER" not in body:
        return ""
    return f"{HEADER}\n{body}"


def _load_state(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def should_inject(agent: str, session: str, pack: str, source: str = "", path: Optional[str] = None) -> bool:
    """True if this pack was not yet injected in this session. Records it. No session id -> always inject."""
    if not session:
        return True
    path = path or _state_path()
    key = f"{agent}:{session}"
    digest = hashlib.sha256(pack.encode("utf-8")).hexdigest()[:16]
    state = _load_state(path)
    if state.get(key, {}).get("h") == digest and source not in ("compact", "clear"):
        return False
    state[key] = {"h": digest, "t": time.time()}
    if len(state) > STATE_KEEP:
        for k, _ in sorted(state.items(), key=lambda kv: kv[1].get("t", 0))[: len(state) - STATE_KEEP]:
            state.pop(k, None)
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(tmp, path)
    except OSError:
        pass
    return True


def format_output(agent: str, pack: str) -> Dict[str, Any]:
    if agent == "antigravity":
        return {"injectSteps": [{"systemMessage": {"systemMessage": pack}}]}
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": pack}}


def run(raw: str, agent: str = "", max_chars: int = 1500, vault_root: Optional[str] = None,
        state_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Pure core: payload text -> output dict, or None for silence. May raise (caller fails open)."""
    payload = json.loads(raw) if raw.strip() else {}
    if not isinstance(payload, dict):
        return None
    agent = detect_agent(payload, agent)
    import memory_engine
    root = vault_root or memory_engine.VAULT_ROOT
    if not root or not os.path.isdir(root):
        return None
    project = resolve_project(payload_cwds(payload), root)
    if not project:
        return None
    pack = build_pack(project, max_chars)
    if not pack:
        return None
    if not should_inject(agent, payload_session(payload), pack, str(payload.get("source") or ""), state_path):
        return None
    return format_output(agent, pack)


def main(argv: Optional[List[str]] = None) -> int:
    try:
        ap = argparse.ArgumentParser()
        ap.add_argument("--agent", default="", choices=["", "claude", "codex", "antigravity"])
        ap.add_argument("--max-chars", type=int, default=1500)
        ap.add_argument("--timeout", type=float, default=3.0)
        a, _ = ap.parse_known_args(argv)
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace").lstrip("﻿")
        box: Dict[str, Any] = {}

        def work() -> None:
            try:
                sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
                box["out"] = run(raw, a.agent, a.max_chars)
            except BaseException:
                box["out"] = None

        t = threading.Thread(target=work, daemon=True)
        t.start()
        t.join(a.timeout)
        out = box.get("out")
        if out:
            sys.stdout.buffer.write(json.dumps(out, ensure_ascii=False).encode("utf-8"))
            sys.stdout.buffer.flush()
    except BaseException:
        pass
    os._exit(0)


if __name__ == "__main__":
    main()
