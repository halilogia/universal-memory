#!/usr/bin/env python3
"""
Universal Memory MCP Server (stdio JSON-RPC 2.0)
Connects Antigravity, Claude Code, and Codex to the Obsidian SQLite FTS5 Memory Vault.
"""

import sys
import json
import logging
from typing import Any, Dict, List

import memory_engine

logging.basicConfig(level=logging.ERROR, stream=sys.stderr)

TOOLS = [
    {
        "name": "memory_search",
        "description": "Obsidian kasasındaki TÜM sohbetleri (Antigravity, ChatGPT, Claude Code) ve kayıtlı kararları MESAJ düzeyinde arar (FTS5 BM25, Türkçe harf katlamalı: 'Kor Saat' = 'Kör Saat'). Her sonuç: id ('dosya.md#satır'), kim yazdı (speaker), ne zaman (when; yerel saat), ajan, oturum, eşleşen satır ve ==vurgulu== özet döner. Tüm kelimeler bulunmazsa kelimelerden herhangi biriyle yedek arama yapar; \"çift tırnak\" tam ifade arar. Her sorguda dizini taze tutar. Tam metin için memory_get(id).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Aranacak anahtar kelimeler (örn. 'Kör Saat Sayacı', 'service worker InvalidStateError'). Birkaç ayırt edici kelime en iyisidir; \"tırnak\" içi tam ifade arar."
                },
                "project": {
                    "type": "string",
                    "description": "Opsiyonel proje filtresi = kasanın üst klasör adı (örn. 'GravityGuard', 'The_Hammer_ve_Godot', 'Antigravity_ve_Yapay_Zeka', 'Windows_ve_Sistem_Araclari'); büyük/küçük harf ve alt çizgiye duyarsız, kısmi eşleşir."
                },
                "limit": {
                    "type": "integer",
                    "description": "Dönecek maksimum sonuç sayısı (varsayılan: 5).",
                    "default": 5
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "memory_get",
        "description": "Kaydı tam metniyle getirir. record_id: memory_search'ün döndürdüğü 'id' ('klasör/dosya.md#satır' = o mesajın tamamı; '#başlangıç:bitiş' = satır aralığı), kayıtlı karar kimliği (örn. 'decision-...') veya dosya yolu. Çıktıda içerik, speaker/tarih/ajan, durum ve Git commit bilgisi bulunur. Çıplak 'readme' veya '2026-10-16' gibi eski kimlikler birden çok nota denk gelir: en yeni not ve 'matches' listesi döner.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "record_id": {
                    "type": "string",
                    "description": "Arama sonucundaki 'id' (örn. 'GravityGuard/[...]/2026-10-16.md#864'), kayıtlı karar kimliği veya dosya yolu."
                }
            },
            "required": ["record_id"]
        }
    },
    {
        "name": "memory_propose",
        "description": "Yeni mimari karar veya öğrenilen ders önerisi: Proje hafızasına yeni bir Markdown dosyası oluşturur ve otomatik Git commit hash'i bağlar (durum: 'proposal').",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "İlgili proje adı (örn. 'GravityGuard', 'ClaudeVideoEditor')."
                },
                "type": {
                    "type": "string",
                    "description": "Kayıt türü: 'decision' (mimari karar), 'lesson' (öğrenilen ders/hata çözümü), 'convention' (kural).",
                    "enum": ["decision", "lesson", "convention"]
                },
                "title": {
                    "type": "string",
                    "description": "Karar veya ders başlığı."
                },
                "content": {
                    "type": "string",
                    "description": "Markdown formatında detaylı açıklama, bağlam, karar ve sonuçlar."
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Etiketler (örn. ['logging', 'performance'])."
                }
            },
            "required": ["project", "type", "title", "content"]
        }
    },
    {
        "name": "memory_commit",
        "description": "Önerilen kararı onaylayıp kalıcılaştırma: Durumu 'proposal' olan kaydı 'canonical' yapar ve FTS5 indeksini günceller.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "record_id": {
                    "type": "string",
                    "description": "Kalıcılaştırılacak kayıt kimliği."
                }
            },
            "required": ["record_id"]
        }
    },
    {
        "name": "memory_handoff",
        "description": "Ajanlar arası oturum devir notu (Handoff): Oturum tamamlandığında veya diğer ajana devrederken alınan kararları, kanıtları ve açık işleri yapısal Markdown olarak kaydeder.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {
                    "type": "string",
                    "description": "İlgili proje adı."
                },
                "summary": {
                    "type": "string",
                    "description": "Oturumda yapılanların özeti."
                },
                "decisions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Bu oturumda alınan temel mimari kararlar."
                },
                "unresolved": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Kalan veya sonraki oturuma devredilen açık görevler."
                }
            },
            "required": ["project", "summary"]
        }
    }
]


def handle_request(req: Dict[str, Any]) -> Dict[str, Any]:
    method = req.get("method")
    req_id = req.get("id")
    params = req.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "serverInfo": {
                    "name": "universal-memory",
                    "version": "1.0.0"
                }
            }
        }

    if method == "notifications/initialized":
        return {}

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": TOOLS
            }
        }

    if method == "tools/call":
        tool_name = params.get("name")
        args = params.get("arguments", {})

        try:
            if tool_name == "memory_search":
                q = args.get("query", "")
                proj = args.get("project")
                lim = args.get("limit", 5)
                res = memory_engine.memory_search(q, project=proj, limit=lim, mode=args.get("mode", "hybrid"))
                text_out = json.dumps(res, ensure_ascii=False, indent=2)

            elif tool_name == "memory_get":
                rid = args.get("record_id", "")
                res = memory_engine.memory_get(rid)
                if not res:
                    text_out = f"Hata: Hafıza kaydı bulunamadı: '{rid}'"
                else:
                    text_out = json.dumps(res, ensure_ascii=False, indent=2)

            elif tool_name == "memory_propose":
                proj = args.get("project", "")
                rtype = args.get("type", "decision")
                title = args.get("title", "")
                content = args.get("content", "")
                tags = args.get("tags", [])
                res = memory_engine.memory_propose(proj, rtype, title, content, tags)
                text_out = json.dumps(res, ensure_ascii=False, indent=2)

            elif tool_name == "memory_commit":
                rid = args.get("record_id", "")
                res = memory_engine.memory_commit(rid)
                text_out = json.dumps(res, ensure_ascii=False, indent=2)

            elif tool_name == "memory_handoff":
                proj = args.get("project", "")
                summary = args.get("summary", "")
                decisions = args.get("decisions", [])
                unresolved = args.get("unresolved", [])
                res = memory_engine.memory_handoff(proj, summary, decisions, unresolved)
                text_out = json.dumps(res, ensure_ascii=False, indent=2)

            else:
                text_out = f"Bilinmeyen araç: {tool_name}"

            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [
                        {
                            "type": "text",
                            "text": text_out
                        }
                    ]
                }
            }
        except Exception as e:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32603,
                    "message": f"Araç çalıştırma hatası: {str(e)}"
                }
            }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {
            "code": -32601,
            "message": f"Desteklenmeyen metod: {method}"
        }
    }


def main():
    # Sync vault once at startup
    try:
        memory_engine.sync_vault()
    except Exception as e:
        sys.stderr.write(f"Universal Memory initial sync failed: {e}\n")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            res = handle_request(req)
            if res:
                sys.stdout.write(json.dumps(res) + "\n")
                sys.stdout.flush()
        except Exception as e:
            sys.stderr.write(f"Protocol error: {e}\n")


if __name__ == "__main__":
    main()
