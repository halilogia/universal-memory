#!/usr/bin/env python3
"""
DevLog Bridge for Universal Memory MCP.
Provides read-only queries into the Obsidian DevLog timeline and session ledger.
"""

import os
import re
import json
import hashlib
from typing import Any, Dict, List, Optional, Tuple

try:
    import yaml
    HAS_YAML = True
except ImportError:
    HAS_YAML = False


def resolve_vault_path() -> Optional[str]:
    """Finds the active Obsidian vault path."""
    configured = os.environ.get("OBSIDIAN_VAULT_PATH", "").strip()
    if configured and os.path.isdir(configured):
        return os.path.abspath(configured)
    fallback = os.path.join(os.path.expanduser("~"), "Desktop", "GitHub", "obsidian")
    if os.path.isdir(fallback):
        return os.path.abspath(fallback)
    return None


def resolve_devlog_repo_path() -> Optional[str]:
    """Finds the local devlog repository path."""
    configured = os.environ.get("DEVLOG_REPO_PATH", "").strip()
    if configured and os.path.isdir(configured):
        return os.path.abspath(configured)
    fallback = os.path.join(os.path.expanduser("~"), "Desktop", "GitHub", "Public", "devlog")
    if os.path.isdir(fallback):
        return os.path.abspath(fallback)
    return None


def devlog_roots(vault: Optional[str] = None, local_dir: Optional[str] = None) -> List[str]:
    """Returns all directories containing devlog files."""
    roots: List[str] = []
    if vault is None:
        vault = resolve_vault_path()

    if vault and os.path.isdir(vault):
        projects_dir = os.path.join(vault, "projects")
        if os.path.isdir(projects_dir):
            try:
                for entry in os.listdir(projects_dir):
                    p_devlogs = os.path.join(projects_dir, entry, "devlogs")
                    if os.path.isdir(p_devlogs):
                        roots.append(p_devlogs)
            except OSError:
                pass
        archive_dir = os.path.join(vault, "_devlogs")
        if os.path.isdir(archive_dir):
            roots.append(archive_dir)

    if local_dir and os.path.isdir(local_dir):
        roots.append(local_dir)
    else:
        repo = resolve_devlog_repo_path()
        if repo:
            repo_devlogs = os.path.join(repo, "devlogs")
            if os.path.isdir(repo_devlogs):
                roots.append(repo_devlogs)

    return roots


def _fallback_parse_yaml(raw_yaml: str) -> Dict[str, Any]:
    """Minimal YAML parser fallback when PyYAML is unavailable."""
    result: Dict[str, Any] = {}
    current_key = None
    list_items = []
    for line in raw_yaml.splitlines():
        trimmed = line.strip()
        if not trimmed or trimmed.startswith("#"):
            continue
        if trimmed.startswith("- "):
            val = trimmed[2:].strip().strip("\"'")
            list_items.append(val)
            if current_key:
                result[current_key] = list_items
            continue
        if ":" in line:
            parts = line.split(":", 1)
            key = parts[0].strip()
            val = parts[1].strip().strip("\"'")
            current_key = key
            list_items = []
            if val == "":
                result[key] = {}
            elif val.lower() == "true":
                result[key] = True
            elif val.lower() == "false":
                result[key] = False
            elif val.isdigit():
                result[key] = int(val)
            else:
                result[key] = val
    return result


def parse_devlog_content(content: str) -> Tuple[Dict[str, Any], str]:
    """Extracts YAML frontmatter and markdown body from a DevLog markdown file."""
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    raw_yaml = parts[1]
    body = parts[2].strip()

    meta: Dict[str, Any] = {}
    if HAS_YAML:
        try:
            meta = yaml.safe_load(raw_yaml) or {}
        except Exception:
            meta = _fallback_parse_yaml(raw_yaml)
    else:
        meta = _fallback_parse_yaml(raw_yaml)

    return meta, body


def devlog_list(project: Optional[str] = None, limit: int = 10, tag: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lists DevLog entries across all discoverable roots."""
    roots = devlog_roots()
    entries_by_id: Dict[str, Dict[str, Any]] = {}

    for root in roots:
        for root_dir, _, files in os.walk(root):
            for file in sorted(files):
                if not file.endswith(".md"):
                    continue
                file_path = os.path.join(root_dir, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        raw = f.read()
                except OSError:
                    continue

                meta, body = parse_devlog_content(raw)
                entry_id = str(meta.get("id") or os.path.splitext(file)[0])
                if entry_id in entries_by_id:
                    continue

                proj = str(meta.get("project") or "")
                if project:
                    target_p = project.lower().replace("-", "").replace("_", "")
                    cand_p = proj.lower().replace("-", "").replace("_", "")
                    if target_p not in cand_p and cand_p not in target_p:
                        continue

                tags = meta.get("tags") or []
                if isinstance(tags, str):
                    tags = [tags]
                if tag and tag.lower() not in [t.lower() for t in tags]:
                    continue

                entries_by_id[entry_id] = {
                    "id": entry_id,
                    "project": proj,
                    "occurredOn": str(meta.get("occurredOn") or ""),
                    "dayNumber": meta.get("dayNumber", 1),
                    "entryNumber": meta.get("entryNumber", 1),
                    "headline": meta.get("headline", ""),
                    "summary": meta.get("summary", ""),
                    "verificationStatus": meta.get("verification", {}).get("status", "unverified") if isinstance(meta.get("verification"), dict) else "unverified",
                    "tags": tags,
                    "schemaVersion": meta.get("schemaVersion", 1),
                    "path": file_path,
                }

    items = list(entries_by_id.values())
    items.sort(
        key=lambda e: (e.get("occurredOn", ""), e.get("entryNumber", 0)),
        reverse=True
    )
    return items[:limit]


def devlog_get(entry_id_or_path: str) -> Dict[str, Any]:
    """Retrieves full DevLog entry by ID or file path."""
    if os.path.isfile(entry_id_or_path):
        try:
            with open(entry_id_or_path, "r", encoding="utf-8") as f:
                raw = f.read()
            meta, body = parse_devlog_content(raw)
            return {
                "id": meta.get("id", os.path.splitext(os.path.basename(entry_id_or_path))[0]),
                "meta": meta,
                "body": body,
                "path": os.path.abspath(entry_id_or_path)
            }
        except OSError as e:
            return {"error": f"Dosya okunamadı: {e}"}

    # Search through devlog roots
    target_id = entry_id_or_path.strip().lower()
    for root in devlog_roots():
        for root_dir, _, files in os.walk(root):
            for file in files:
                if not file.endswith(".md"):
                    continue
                file_path = os.path.join(root_dir, file)
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        raw = f.read()
                except OSError:
                    continue

                meta, body = parse_devlog_content(raw)
                entry_id = str(meta.get("id", "")).lower()
                base_name = os.path.splitext(file)[0].lower()
                if entry_id == target_id or base_name == target_id:
                    return {
                        "id": meta.get("id", base_name),
                        "meta": meta,
                        "body": body,
                        "path": os.path.abspath(file_path)
                    }

    return {"error": f"DevLog kaydı bulunamadı: {entry_id_or_path}"}


def _resolve_ledger_path() -> Optional[str]:
    """Locates the .analysis_ledger.json storage."""
    repo = resolve_devlog_repo_path()
    if repo:
        p = os.path.join(repo, ".analysis_ledger.json")
        if os.path.exists(p):
            return p
    app_data = os.environ.get("LOCALAPPDATA", "")
    if app_data:
        p = os.path.join(app_data, "DevLog", "analysis_ledger.json")
        if os.path.exists(p):
            return p
    return None


def devlog_check_session(conversation_id: str, transcript_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Checks conversation status against the DevLog incremental analysis ledger.
    Returns status: 'NEW' | 'UP_TO_DATE' | 'DELTA' | 'INVALIDATED'.
    """
    ledger_path = _resolve_ledger_path()
    ledger_data: Dict[str, Any] = {}
    if ledger_path and os.path.isfile(ledger_path):
        try:
            with open(ledger_path, "r", encoding="utf-8") as f:
                ledger_data = json.load(f)
        except Exception:
            pass

    record = ledger_data.get(conversation_id)
    if not record:
        return {
            "conversationId": conversation_id,
            "status": "NEW",
            "message": "Bu oturum henüz DevLog için analiz edilmemiştir.",
            "record": None
        }

    # If transcript is provided, inspect message delta
    if transcript_path and os.path.isfile(transcript_path):
        try:
            messages = []
            with open(transcript_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        messages.append(json.loads(line))

            total_count = len(messages)
            last_count = record.get("lastAnalyzedMessageCount", 0)

            if total_count == last_count:
                return {
                    "conversationId": conversation_id,
                    "status": "UP_TO_DATE",
                    "message": "Oturum tamamen güncel. Yeni mesaj yok (0 token).",
                    "totalMessages": total_count,
                    "lastAnalyzedOn": record.get("analyzedAt"),
                    "record": record
                }
            elif total_count > last_count:
                delta_count = total_count - last_count
                return {
                    "conversationId": conversation_id,
                    "status": "DELTA",
                    "message": f"Oturumda {delta_count} adet yeni analiz edilmemiş mesaj var.",
                    "totalMessages": total_count,
                    "analyzedMessages": last_count,
                    "newMessages": delta_count,
                    "lastAnalyzedOn": record.get("analyzedAt"),
                    "record": record
                }
        except Exception as e:
            return {
                "conversationId": conversation_id,
                "status": "ERROR",
                "message": f"Transcript okuma hatası: {e}",
                "record": record
            }

    return {
        "conversationId": conversation_id,
        "status": "RECORDED",
        "message": f"Oturum daha önce analiz edilmiş ({record.get('lastAnalyzedMessageCount', 0)} mesaj).",
        "lastAnalyzedOn": record.get("analyzedAt"),
        "devlogId": record.get("devlogId"),
        "record": record
    }
