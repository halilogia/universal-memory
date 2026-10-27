# 🏛️ Universal Memory Mimarisi (ARCHITECTURE.md)

Universal Memory; Antigravity, Claude Code ve Codex arasında paylaşılan, Git-benzeri iki aşamalı (propose/commit) çalışan kalıcı yapay zeka hafıza motorudur.

---

## 🧩 Katmanlar ve Bileşenler

```
universal-memory/
├── server.py           # Model Context Protocol (MCP) sunucusu (stdio üzerinden JSON-RPC)
├── memory_engine.py    # İki aşamalı öneri/onay döngüsü (propose, commit, handoff)
├── memory_index.py     # SQLite FTS5 tam metin araması ve Obsidian Markdown senkronizasyonu
├── distillation/       # Oturum sonu bilgi damıtma ve özetleme algoritmaları
└── schemas/            # Bellek kayıtları ve metadata JSON şemaları
```

---

## ⚡ İki Aşamalı Hafıza Döngüsü (Two-Phase Commit)

```mermaid
sequenceDiagram
    participant Agent as Yapay Zeka Ajanı (Antigravity/Claude)
    participant Engine as Memory Engine
    participant SQLite as SQLite FTS5 Deposu
    participant Vault as Obsidian Vault (.md)

    Agent->>Engine: memory_propose(title, content, tags)
    Engine-->>Agent: proposal_id & diff önizleme
    Note over Agent,Engine: Ajan veya İnsan doğrulaması
    Agent->>Engine: memory_commit(proposal_id)
    Engine->>SQLite: Atomik transaction kaydı
    Engine->>Vault: Markdown dosyası olarak diske yaz
    Engine-->>Agent: Onaylandı ve dizine eklendi (status: OK)
```

---

## 🛡️ Dokunulmaz Kurallar
1. **İki Aşamalı Yazma Güvencesi:** Ajanlar doğrudan kalıcı hafızaya körlemesine yazamaz; önce `propose` ile teklif edilir, doğrulandıktan sonra `commit` edilir.
2. **Kişisel Veri ve Gizlilik:** API anahtarları, şifreler ve oturum tokenları bellek indeksine kaydedilemez.

## ⏳ Bi-Temporal Model, Çelişki Çözümü ve Bağlam (v2.0)

| Kavram | Alan / Modül | Davranış |
|---|---|---|
| Geçerlilik zamanı | `valid_from` .. `valid_until` | `[from, until)` yarı açık; boş uç = açık. Alanı olmayan kayıt (sohbet) her zaman geçerli |
| İşlem zamanı | `ingestion_time`, `source_event_time` | Sistemin öğrendiği an / olayın gerçekleştiği an |
| Geçersiz kılma | `superseded_by`, `status: superseded`, `- supersedes: [[id]]` | Silme yok; zincir korunur |
| Zaman yolculuğu | `memory_search(as_of, include_invalid)` | Varsayılan: yalnızca şimdi geçerli olanlar |
| Çelişki çözümü | `conflict_resolver.analyze` | `reject_duplicate` / `supersede_candidates` / `create` |
| Hızlı yakalama | `quick_capture` | Önek → tür; canonical; çelişen eski kayıt anında kapanır |
| Damıtma | `distillation/worker.py` | Regex (negatif/karar/kural/görev) + opsiyonel yerel model |
| Bağlam paketi | `context_injector.build_context` | Geçerli kartlar, sorgu ilgisi, karakter bütçesi, agent_id kapsamı |

Akış: `memory_propose` → `conflict_resolver` (duplicate ise dur) → dosya `contradicts` bağlarıyla yazılır → `memory_commit` → çelişen canonical kayıtlar `bitemporal.supersede` ile kapatılır → indeks senkronize.

Tasarım notları: Graphiti'den bi-temporal pencere ve geçersiz kılma, Mem0'dan kapsam (`agent_id`/`run_id`) ve ekleme anında ADD/UPDATE/NONE kararı alındı. Çözücü deterministiktir (gömme/LLM yok); semantik benzerlik gerekirse `classify` arkasına eklenebilir. Avenox Beyin transkript damıtmaz (ajan kendi not yazar, `yakala` içerik yakalar); transkript damıtma bu repoda `worker.py` ile yapılır.
