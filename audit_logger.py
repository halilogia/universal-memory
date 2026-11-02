"""Universal Memory MCP: Zero-Maintenance Audit & Telemetry Logger.

Bu modül, MCP araç çağrılarını (search, get, propose, capture, commit vb.)
yerel olarak JSONL formatında rotasyonlu (maks 5MB, 2 yedek) kaydeder.
Git'e asla yüklenmez (.gitignore korumalıdır) ve haftalık manuel bakım gerektirmez.
"""
from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Varsayılan log konumu: Obsidian vault içindeki .index dizini veya fallback
_DEFAULT_DIR: Optional[str] = None
_LOGGER: Optional[logging.Logger] = None
_MAX_BYTES = 5 * 1024 * 1024  # 5 MB
_BACKUP_COUNT = 2             # max 2 yedek (audit.jsonl.1, audit.jsonl.2 -> toplam maks 15 MB)
_MAX_ARG_STRING_LEN = 300     # Log satırlarının şişmesini önlemek için argüman metni tavanı


def get_log_dir() -> str:
    """Log dizinini belirler ve oluşturur."""
    global _DEFAULT_DIR
    if _DEFAULT_DIR and os.path.isdir(_DEFAULT_DIR):
        return _DEFAULT_DIR

    # 1. Tercih: Obsidian vault .index dizini
    try:
        home = os.path.expanduser("~")
        candidate = os.path.join(home, "Desktop", "GitHub", "obsidian", ".index")
        if os.path.exists(candidate) or os.path.exists(os.path.join(home, "Desktop", "GitHub", "obsidian")):
            os.makedirs(candidate, exist_ok=True)
            _DEFAULT_DIR = candidate
            return _DEFAULT_DIR
    except Exception:
        pass

    # 2. Tercih: Repo içi logs/ dizini
    try:
        repo_dir = os.path.dirname(os.path.abspath(__file__))
        candidate = os.path.join(repo_dir, "logs")
        os.makedirs(candidate, exist_ok=True)
        _DEFAULT_DIR = candidate
        return _DEFAULT_DIR
    except Exception:
        pass

    # 3. Fallback: Kullanıcı geçici klasörü
    candidate = os.path.join(os.path.expanduser("~"), ".gemini", "universal-memory-logs")
    os.makedirs(candidate, exist_ok=True)
    _DEFAULT_DIR = candidate
    return _DEFAULT_DIR


def get_log_filepath() -> str:
    """Aktif log dosya yolunu döndürür."""
    return os.path.join(get_log_dir(), "audit.jsonl")


def _get_audit_logger(filepath: Optional[str] = None) -> logging.Logger:
    """Döngüsel (Rotating) JSONL loglayıcıyı başlatır."""
    target_path = filepath or get_log_filepath()
    logger_name = f"universal_memory_audit_{target_path}"
    logger = logging.getLogger(logger_name)

    if not logger.handlers:
        logger.setLevel(logging.INFO)
        logger.propagate = False
        try:
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            handler = RotatingFileHandler(
                target_path,
                maxBytes=_MAX_BYTES,
                backupCount=_BACKUP_COUNT,
                encoding="utf-8"
            )
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
        except Exception as e:
            # Disk doluluğu veya izin hatası durumunda stderr'e fısılda ama uygulamayı asla düşürme
            sys.stderr.write(f"[UniversalMemory:AuditLogger] Handler oluşturulamadı: {e}\n")

    return logger


def _sanitize_args(args: Any) -> Any:
    """Log kirliliğini önlemek için uzun metinleri budar ve hassas anahtarları filtreler."""
    if isinstance(args, dict):
        sanitized = {}
        for k, v in args.items():
            if k.lower() in ("token", "password", "secret", "auth", "api_key", "authorization"):
                sanitized[k] = "***MASKED***"
            else:
                sanitized[k] = _sanitize_args(v)
        return sanitized
    elif isinstance(args, list):
        return [_sanitize_args(item) for item in args[:20]]
    elif isinstance(args, str):
        if len(args) > _MAX_ARG_STRING_LEN:
            return args[:_MAX_ARG_STRING_LEN] + f"... [truncated +{len(args) - _MAX_ARG_STRING_LEN} chars]"
        return args
    return args


def log_tool_event(
    tool_name: str,
    args: Optional[Dict[str, Any]] = None,
    duration_ms: float = 0.0,
    status: str = "ok",
    error_message: Optional[str] = None,
    summary: Optional[str] = None,
    custom_filepath: Optional[str] = None
) -> None:
    """Tek bir araç çağrısını non-blocking ve fail-safe şekilde JSONL olarak kaydeder."""
    try:
        logger = _get_audit_logger(custom_filepath)
        if not logger.handlers:
            return

        now = datetime.now(timezone.utc).astimezone().isoformat()
        clean_args = _sanitize_args(args or {})

        entry = {
            "ts": now,
            "tool": tool_name,
            "duration_ms": round(duration_ms, 2),
            "status": status,
            "project": clean_args.get("project") if isinstance(clean_args, dict) else None,
            "args": clean_args,
        }
        if summary:
            entry["summary"] = summary
        if error_message:
            entry["error"] = error_message

        line = json.dumps(entry, ensure_ascii=False)
        logger.info(line)
    except Exception:
        # Asla ana MCP akışını durdurma (Fail-safe)
        pass
