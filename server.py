#!/usr/bin/env python3
"""
Universal Memory MCP Server (stdio JSON-RPC 2.0)
Connects Antigravity, Claude Code, and Codex to the Obsidian SQLite FTS5 Memory Vault.
"""

import sys
import json
import logging
import importlib.util
from typing import Any, Dict, List

# Dağıtılmış kopyada bu dosyalardan biri eksikse hata ilk memory_* çağrısında
# ("No module named ...") patlıyordu. Açılışta kontrol edip eksikleri adıyla söyle.
REQUIRED_MODULES = (
    "memory_engine", "memory_index", "bitemporal",
    "conflict_resolver", "context_injector", "hook_context", "second_brain",
)


def _verify_install() -> None:
    missing = [m for m in REQUIRED_MODULES if importlib.util.find_spec(m) is None]
    if missing:
        sys.stderr.write(
            "universal-memory: eksik modül(ler): " + ", ".join(m + ".py" for m in missing)
            + "\nÇözüm: repoda `python tools/sync_deploy.py --apply` çalıştır.\n"
        )
        sys.exit(1)


_verify_install()

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
                },
                "as_of": {
                    "type": "string",
                    "description": "Zaman yolculuğu: ISO tarih/saat. O anda GEÇERLİ olan kayıtları döndürür (varsayılan: şimdi)."
                },
                "include_invalid": {
                    "type": "boolean",
                    "description": "true ise geçersiz kılınmış (superseded) kayıtlar da döner (tarihçe).",
                    "default": False
                },
                "order_by": {
                    "type": "string",
                    "enum": ["relevance", "time_asc", "time_desc"],
                    "description": "Sonuç sıralaması: 'relevance' (varsayılan BM25), 'time_asc' (eskiden yeniye kronolojik), 'time_desc' (en yeniden en eskiye).",
                    "default": "relevance"
                },
                "surround": {
                    "type": "integer",
                    "description": "Eşleşen mesajın öncesinden ve sonrasından eklenecek çevreleyen satır sayısı (örn. 3 veya 5); asistan yanıtını doğrudan 'context' alanında döner.",
                    "default": 0
                },
                "context_lines": {
                    "type": "integer",
                    "description": "surround ile aynı (çevreleyen satır sayısı takma adı)."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "memory_get",
        "description": "Kaydı tam metniyle getirir. id / record_id: memory_search'ün döndürdüğü 'id' ('klasör/dosya.md#satır' = o mesajın tamamı; '#başlangıç:bitiş' = satır aralığı), kayıtlı karar kimliği (örn. 'decision-...') veya dosya yolu. Çıktıda içerik, speaker/tarih/ajan, durum ve Git commit bilgisi bulunur. Çıplak 'readme' veya '2026-10-16' gibi eski kimlikler birden çok nota denk gelir: en yeni not ve 'matches' listesi döner.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "record_id": {
                    "type": "string",
                    "description": "Arama sonucundaki 'id' (örn. 'GravityGuard/[...]/2026-10-16.md#864'), kayıtlı karar kimliği veya dosya yolu."
                },
                "id": {
                    "type": "string",
                    "description": "record_id için takma ad (örn. 'dosya.md#241' veya karar kimliği)."
                },
                "surround": {
                    "type": "integer",
                    "description": "Opsiyonel çevreleyen satır sayısı (örn. 3 veya 5). Belirtilen satır aralığını genişletir.",
                    "default": 0
                },
                "context_lines": {
                    "type": "integer",
                    "description": "surround için takma ad."
                }
            }
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
                },
                "force": {
                    "type": "boolean",
                    "description": "true ise tekrar (duplicate) tespitine rağmen yaz.",
                    "default": False
                },
                "agent_id": {"type": "string", "description": "Kapsam: kaydı üreten/yalnız onun kullanacağı ajan."},
                "run_id": {"type": "string", "description": "Kapsam: oturum/çalıştırma kimliği."}
            },
            "required": ["project", "type", "title", "content"]
        }
    },
    {
        "name": "memory_capture",
        "description": "Hızlı tek satırlık yakalama (yakala). Önek türü belirler: 'karar:', 'kural:', 'ders:', 'olmadı:' (negatif bilgi); öneksiz = karar. Doğrudan canonical yazılır; tekrar/çelişki denetlenir, çelişen eski kayıt geçersiz kılınır (silinmez).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "Proje adı."},
                "text": {"type": "string", "description": "Tek satırlık not (örn. 'olmadı: FTS tabanlı dedup 500ms üstüne çıktı')."},
                "tags": {"type": "array", "items": {"type": "string"}},
                "agent_id": {"type": "string"},
                "run_id": {"type": "string"}
            },
            "required": ["project", "text"]
        }
    },
    {
        "name": "memory_supersede",
        "description": "Eski kaydı geçersiz kıl: valid_until kapatılır, superseded_by yeni kayda bağlanır. Kayıt silinmez, zaman çizelgesi korunur.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "old_id": {"type": "string", "description": "Geçersiz kılınacak kayıt."},
                "new_id": {"type": "string", "description": "Yerine geçen kayıt."},
                "when": {"type": "string", "description": "Opsiyonel ISO zaman (varsayılan: şimdi)."}
            },
            "required": ["old_id", "new_id"]
        }
    },
    {
        "name": "memory_context",
        "description": "OpenCode/yerel modeller için tek kompakt bağlam paketi: yalnızca geçerli (invalidation görmemiş) kural, karar, ders, negatif bilgi ve son handoff'taki açık işler; sorguya göre sıralanır, karakter bütçesine sığdırılır.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string"},
                "query": {"type": "string", "description": "İlgililik için görev/konu metni."},
                "max_chars": {"type": "integer", "default": 3000},
                "as_of": {"type": "string", "description": "Opsiyonel zaman yolculuğu."},
                "agent_id": {"type": "string"}
            },
            "required": ["project"]
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
    },
    {
        "name": "memory_ingest",
        "description": "Second Brain / Damıt: ham içeriği (YouTube transkripti, makale, ses dökümü, uzun doküman) Kademeli Özetleme ile atomik karta çevirir: Executive Summary (2-3 cümle), Core Takeaways (3-5 çıkarım, aksiyonlar '- [ ]'), Key Quotes / Extracted Insights; ham metinde **kalın** (1. katman) ve ==vurgu== (2. katman). Çıkarım deterministiktir (kaynaktan birebir cümleler, LLM yok). 'projects/<proje>/resources/' (veya lessons/) altına canonical yazar, FTS5'e ekler, Git HEAD hash'ini (source_commit) ve içerik SHA-256'sını mühürler, ilişkili mevcut notlara [[bağ]] ekler. Aynı içerik tekrar eklenmez; gizli anahtarlar maskelenir.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "İlgili proje adı."},
                "title": {"type": "string", "description": "Kaynak başlığı (boşsa ilk özet cümlesinden türetilir)."},
                "content": {"type": "string", "description": "Ham içerik (transkript, makale metni, doküman)."},
                "source_type": {
                    "type": "string",
                    "enum": ["text", "youtube", "article", "audio_transcript"],
                    "description": "Kaynak türü.",
                    "default": "text"
                },
                "tags": {"type": "array", "items": {"type": "string"}, "description": "Etiketler; en sık 3 anahtar kelime otomatik eklenir."},
                "save_as": {
                    "type": "string",
                    "enum": ["resource", "lesson"],
                    "description": "Kayıt klasörü: 'resource' (resources/, varsayılan) veya 'lesson' (lessons/).",
                    "default": "resource"
                },
                "force": {"type": "boolean", "description": "true ise aynı içerik daha önce eklenmiş olsa da yaz.", "default": False}
            },
            "required": ["project", "title", "content"]
        }
    },
    {
        "name": "memory_graph",
        "description": "Second Brain / Organize: projedeki geçerli karar (decisions/), ders (lessons/), kaynak (resources/) ve kuralları ortak etiket + anahtar kelime ile çapraz bağlar (açık [[wikilink]] ve supersedes/contradicts kenarları da dahil), kümeler ve 'Map of Content (MOC)' Markdown'ı döner (Obsidian graf uyumlu: [[DECISION-xxx]], [[LESSON-yyy]]). Merkez notları ve bağlantısız notları listeler. 'topic' verilirse yalnız o konudaki notlar ve komşuları.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "İlgili proje adı."},
                "topic": {"type": "string", "description": "Opsiyonel konu filtresi (örn. 'logging', 'sprite sheet')."}
            },
            "required": ["project"]
        }
    },
    {
        "name": "memory_express",
        "description": "Second Brain / İfade: projedeki kararları, dersleri, kaynakları ve handoff'ları derleyip insan/geliştirici çıktısı üretir (Markdown): 'adr_report' (ADR numaralı rapor; geçersiz kılınanlar durumuyla birlikte), 'release_notes' (kararlar, dersler, geçersiz kılınanlar, handoff özetleri, açık işler), 'project_brief' (kurallar, aktif kararlar, denenip çalışmayanlar, açık işler, bilgi haritası).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "description": "İlgili proje adı."},
                "output_type": {
                    "type": "string",
                    "enum": ["adr_report", "release_notes", "project_brief"],
                    "description": "Çıktı türü.",
                    "default": "adr_report"
                },
                "topic": {"type": "string", "description": "Opsiyonel konu filtresi."},
                "since": {"type": "string", "description": "Opsiyonel (release_notes): bu tarihten (YYYY-MM-DD) sonraki kayıtlar."}
            },
            "required": ["project"]
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
                    "version": "2.0.0"
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
                surr = args.get("surround")
                if surr is None:
                    surr = args.get("context_lines", 0)
                res = memory_engine.memory_search(
                    q, project=proj, limit=lim, mode=args.get("mode", "hybrid"),
                    as_of=args.get("as_of"), include_invalid=bool(args.get("include_invalid", False)),
                    order_by=args.get("order_by", "relevance"),
                    surround=int(surr or 0)
                )
                text_out = json.dumps(res, ensure_ascii=False, indent=2)

            elif tool_name == "memory_get":
                rid = args.get("record_id") or args.get("id") or args.get("path") or ""
                surr = args.get("surround") or args.get("context_lines") or 0
                res = memory_engine.memory_get(rid, surround=int(surr or 0))
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
                res = memory_engine.memory_propose(proj, rtype, title, content, tags, force=bool(args.get("force", False)),
                                                   agent_id=args.get("agent_id", ""), run_id=args.get("run_id", ""))
                text_out = json.dumps(res, ensure_ascii=False, indent=2)

            elif tool_name == "memory_capture":
                res = memory_engine.quick_capture(args.get("project", ""), args.get("text", ""), args.get("tags", []),
                                                  agent_id=args.get("agent_id", ""), run_id=args.get("run_id", ""))
                text_out = json.dumps(res, ensure_ascii=False, indent=2)

            elif tool_name == "memory_supersede":
                res = memory_engine.memory_supersede(args.get("old_id", ""), args.get("new_id", ""), args.get("when"))
                text_out = json.dumps(res, ensure_ascii=False, indent=2)

            elif tool_name == "memory_context":
                import context_injector
                res = context_injector.build_context(args.get("project", ""), args.get("query", ""),
                                                     int(args.get("max_chars", 3000)), args.get("as_of"),
                                                     args.get("agent_id", ""))
                text_out = res["text"]

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

            elif tool_name == "memory_ingest":
                import second_brain
                res = second_brain.ingest(args.get("project", ""), args.get("title", ""), args.get("content", ""),
                                          args.get("source_type", "text"), args.get("tags", []),
                                          save_as=args.get("save_as", "resource"), force=bool(args.get("force", False)))
                text_out = json.dumps(res, ensure_ascii=False, indent=2)

            elif tool_name in ("memory_graph", "memory_express"):
                import second_brain
                if tool_name == "memory_graph":
                    res = second_brain.graph(args.get("project", ""), args.get("topic"))
                else:
                    res = second_brain.express(args.get("project", ""), args.get("output_type", "adr_report"),
                                               args.get("topic"), args.get("since"))
                text_out = res["markdown"] if res.get("success") else json.dumps(res, ensure_ascii=False, indent=2)

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
